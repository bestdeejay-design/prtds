"""Leads module — the path from intention to a delivered request (§06, §07).

Hard rules implemented here
---------------------------
* WhatsApp is a first-class transition from intention to deal, not a decorative
  "contact" button: the deep link carries a pre-composed message with the
  product/service, the order parameters and a **reference of the request**.
* PRTDS sees the fact of an initiated transition but has no right to treat it as
  a completed sale without independent confirmation — so ``whatsapp_click`` and
  ``lead_submitted`` are different events with different meaning.
* Consent precedes transferring contacts to the seller (§13.4).
* Submission is idempotent: one request never becomes two leads, and therefore
  never becomes two commissions.
* Private correspondence is never read or stored — only the message the user
  asked PRTDS to compose.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.funnel import EventType
from app.core.ids import hash_pii, new_id, ref_code as build_ref_code, stable_hash, utcnow
from app.core.money import format_pyg
from app.domain.models import (
    ActorKind,
    Branch,
    ChannelType,
    Company,
    Consent,
    ConsentPurpose,
    Contact,
    Lead,
    LeadIntent,
    LeadStatus,
    Offer,
    PartnerUser,
    PublicationStatus,
)
from app.modules import funnel as funnel_service

#: CRM lifecycle. Manual reconciliation may reverse a rejection with a note —
#: partners in Paraguay often answer by phone later (§07).
ALLOWED_TRANSITIONS: dict[LeadStatus, set[LeadStatus]] = {
    LeadStatus.SUBMITTED: {
        LeadStatus.ACCEPTED,
        LeadStatus.REJECTED,
        LeadStatus.CANCELLED,
        LeadStatus.EXPIRED,
    },
    LeadStatus.ACCEPTED: {
        LeadStatus.BOOKED,
        LeadStatus.VISIT_DONE,
        LeadStatus.SALE_CONFIRMED,
        LeadStatus.CANCELLED,
        LeadStatus.REJECTED,
    },
    LeadStatus.BOOKED: {
        LeadStatus.VISIT_DONE,
        LeadStatus.SALE_CONFIRMED,
        LeadStatus.CANCELLED,
    },
    LeadStatus.VISIT_DONE: {LeadStatus.SALE_CONFIRMED, LeadStatus.CANCELLED},
    LeadStatus.REJECTED: {LeadStatus.ACCEPTED},
    LeadStatus.CANCELLED: {LeadStatus.ACCEPTED},
    LeadStatus.EXPIRED: {LeadStatus.ACCEPTED},
    LeadStatus.SALE_CONFIRMED: set(),
}

_STATUS_EVENT: dict[LeadStatus, EventType] = {
    LeadStatus.ACCEPTED: EventType.LEAD_ACCEPTED,
    LeadStatus.REJECTED: EventType.LEAD_REJECTED,
    LeadStatus.CANCELLED: EventType.LEAD_CANCELLED,
    LeadStatus.BOOKED: EventType.BOOKING_CONFIRMED,
    LeadStatus.VISIT_DONE: EventType.VISIT_DONE,
}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    value = _aware(value)
    return value.isoformat() if value else None


# --------------------------------------------------------------------------- #
# Resolution helpers — published data only
# --------------------------------------------------------------------------- #
def resolve_company(session: Session, slug: str) -> Company:
    company = session.scalar(
        select(Company).where(
            Company.slug == slug, Company.publication_status == PublicationStatus.PUBLISHED
        )
    )
    if company is None:
        raise LookupError(f"empresa no publicada o inexistente: {slug}")
    return company


def resolve_branch(session: Session, company: Company, branch_id: str | None) -> Branch:
    branches = [b for b in company.branches if b.publication_status.is_public]
    if not branches:
        raise LookupError("la empresa no tiene sucursales publicadas")
    if branch_id:
        branch = next((b for b in branches if b.id == branch_id), None)
        if branch is None:
            raise LookupError(f"sucursal no publicada: {branch_id}")
        return branch
    return branches[0]


def resolve_offer(session: Session, company: Company, offer_id: str | None) -> Offer | None:
    if not offer_id:
        return None
    offer = session.scalar(
        select(Offer).where(
            Offer.id == offer_id, Offer.company_id == company.id, Offer.is_active.is_(True)
        )
    )
    if offer is None:
        raise LookupError(f"oferta inexistente o inactiva: {offer_id}")
    return offer


def whatsapp_number(branch: Branch) -> str | None:
    if branch.whatsapp_e164:
        return branch.whatsapp_e164
    primary = next(
        (c for c in branch.contacts if c.channel is ChannelType.WHATSAPP and c.is_primary), None
    )
    if primary is None:
        primary = next((c for c in branch.contacts if c.channel is ChannelType.WHATSAPP), None)
    return primary.value if primary else None


def _digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def next_ref_code(session: Session, when: datetime | None = None) -> str:
    when = when or utcnow()
    count = session.scalar(select(func.count(Lead.id))) or 0
    for attempt in range(count + 1, count + 500):
        candidate = build_ref_code(attempt, when)
        exists = session.scalar(select(Lead.id).where(Lead.ref_code == candidate))
        if not exists:
            return candidate
    return build_ref_code(count + 1, when) + "-" + stable_hash(utcnow().isoformat())[:4].upper()


def contact_ref(prefix: str = "WA") -> str:
    """Short reference of a request, used in the pre-composed WhatsApp message
    so a partner can reconcile a manual sale later (§07)."""
    now = utcnow()
    return f"{prefix}-{now.strftime('%y%m')}-{stable_hash(now.isoformat())[:6].upper()}"


# --------------------------------------------------------------------------- #
# Consent (§13.4)
# --------------------------------------------------------------------------- #
def register_consent(
    session: Session,
    *,
    purpose: ConsentPurpose,
    granted: bool,
    subject_ref: str | None = None,
    channel: str | None = None,
    text_version: str = "v1",
) -> Consent:
    consent = Consent(
        id=new_id("consent"),
        subject_kind="user" if subject_ref else "anonymous",
        subject_hash=hash_pii(subject_ref) if subject_ref else None,
        purpose=purpose,
        granted=granted,
        granted_at=utcnow(),
        channel=channel,
        text_version=text_version,
        evidence={"registered_by": "api", "locale": "es-PY"},
    )
    session.add(consent)
    session.flush()
    return consent


# --------------------------------------------------------------------------- #
# Message composition
# --------------------------------------------------------------------------- #
def compose_message(
    company: Company,
    branch: Branch,
    offer: Offer | None,
    *,
    reference: str,
    custom: str | None = None,
    requested_at: str | None = None,
    params: dict | None = None,
) -> str:
    """Pre-composed message: product/service, order parameters, request id."""
    parts = [f"Hola {company.display_name}, vi su ficha en PRTDS."]
    if offer:
        price = format_pyg(offer.base_price - (offer.seller_discount or 0), with_symbol=True)
        parts.append(f"Me interesa: {offer.title_es} ({price}).")
    else:
        parts.append(f"Consulta sobre sus productos/servicios en {branch.name_es}.")
    if requested_at:
        parts.append(f"Fecha/horario deseado: {requested_at}.")
    if params:
        details = ", ".join(f"{k}: {v}" for k, v in params.items() if v)
        if details:
            parts.append(f"Detalles: {details}.")
    if custom:
        parts.append(custom.strip())
    parts.append(f"Ref: {reference}.")
    return " ".join(parts)


def build_whatsapp_link(
    session: Session,
    *,
    company_slug: str,
    branch_id: str | None = None,
    offer_id: str | None = None,
    message: str | None = None,
    session_ref: str | None = None,
    actor_ref: str | None = None,
    source: str | None = None,
    campaign_id: str | None = None,
    utm: dict | None = None,
) -> dict[str, Any]:
    """Create the WhatsApp transition and log it as an *attempt*.

    The event proves an initiated transition only; it is never a sale and never
    creates a commission (§06, §07).
    """
    company = resolve_company(session, company_slug)
    branch = resolve_branch(session, company, branch_id)
    offer = resolve_offer(session, company, offer_id)

    number = whatsapp_number(branch)
    if not number:
        alternatives = [
            {"channel": contact.channel.value, "value": contact.value}
            for contact in branch.contacts
            if contact.channel is not ChannelType.WHATSAPP
        ]
        # branch-level fields are channels too (a landline is a real alternative)
        known = {item["value"] for item in alternatives}
        for channel, value in (
            ("phone", branch.phone_e164),
            ("email", branch.email),
            ("website", branch.website_url),
            ("instagram", branch.instagram_handle),
        ):
            if value and value not in known:
                alternatives.append({"channel": channel, "value": value})
        raise LookupError(
            f"esta sucursal no tiene WhatsApp verificado; canales alternativos: "
            + ", ".join(f"{item['channel']} ({item['value']})" for item in alternatives)
            if alternatives
            else "esta sucursal no tiene canales de contacto publicados"
        )

    reference = contact_ref("WA")
    text = message or compose_message(
        company, branch, offer, reference=reference
    )
    url = f"https://wa.me/{_digits(number)}?text={quote(text)}"

    result = funnel_service.record_event(
        session,
        EventType.WHATSAPP_CLICK,
        company_id=company.id,
        branch_id=branch.id,
        offer_id=offer.id if offer else None,
        actor_ref=actor_ref,
        session_ref=session_ref,
        source=source or "card",
        campaign_id=campaign_id,
        utm=utm,
        evidence={"ref": reference, "channel": "whatsapp"},
    )
    session.flush()

    return {
        "url": url,
        "reference": reference,
        "message": text,
        "company": {"slug": company.slug, "display_name": company.display_name},
        "branch": {"id": branch.id, "name_es": branch.name_es, "barrio": branch.barrio},
        "offer": {"id": offer.id, "title_es": offer.title_es} if offer else None,
        "event_id": result.event.id,
        "deduplicated": result.deduplicated,
        "disclaimer_es": (
            "Este clic registra un intento de contacto. No es una venta confirmada "
            "y no genera comisión por sí solo."
        ),
    }


def build_call_link(
    session: Session,
    *,
    company_slug: str,
    branch_id: str | None = None,
    session_ref: str | None = None,
    actor_ref: str | None = None,
    source: str | None = None,
    campaign_id: str | None = None,
    utm: dict | None = None,
) -> dict[str, Any]:
    company = resolve_company(session, company_slug)
    branch = resolve_branch(session, company, branch_id)
    phone = branch.phone_e164 or next(
        (c.value for c in branch.contacts if c.channel is ChannelType.PHONE), None
    )
    if not phone:
        raise LookupError("esta sucursal no tiene teléfono publicado")

    reference = contact_ref("LL")
    result = funnel_service.record_event(
        session,
        EventType.CALL_CLICK,
        company_id=company.id,
        branch_id=branch.id,
        actor_ref=actor_ref,
        session_ref=session_ref,
        source=source or "card",
        campaign_id=campaign_id,
        utm=utm,
        evidence={"ref": reference, "channel": "phone"},
    )
    session.flush()
    return {
        "url": f"tel:{_digits(phone)}",
        "phone": phone,
        "reference": reference,
        "event_id": result.event.id,
        "disclaimer_es": "Registro de intento de llamada; no confirma una conversación atendida.",
    }


# --------------------------------------------------------------------------- #
# Lead submission
# --------------------------------------------------------------------------- #
def submit_lead(
    session: Session,
    payload: dict[str, Any],
    *,
    session_ref: str | None = None,
    actor_ref: str | None = None,
    idempotency_header: str | None = None,
) -> tuple[Lead, bool]:
    """Deliver a request to the seller.

    Idempotent: the same person asking the same company about the same offer on
    the same day is one lead, not several (§13.4).
    """
    consent_in = payload.get("consent") or {}
    if not consent_in.get("granted", False):
        raise PermissionError(
            "se requiere consentimiento explícito para transferir el contacto al vendedor"
        )

    company = resolve_company(session, payload["company_slug"])
    branch = resolve_branch(session, company, payload.get("branch_id"))
    offer = resolve_offer(session, company, payload.get("offer_id"))

    consent = register_consent(
        session,
        purpose=ConsentPurpose(consent_in.get("purpose", ConsentPurpose.LEAD_TRANSFER.value)),
        granted=True,
        subject_ref=consent_in.get("subject_ref") or payload.get("customer_phone"),
        channel=consent_in.get("channel") or "web",
    )

    phone = payload.get("customer_phone")
    phone_hash = hash_pii(phone) if phone else None
    day = utcnow().strftime("%Y%m%d")
    derived_key = stable_hash(
        "lead",
        company.id,
        branch.id,
        offer.id if offer else None,
        phone_hash or hash_pii((payload.get("customer_name") or "") + (payload.get("message") or "")),
        day,
    )
    key = idempotency_header or payload.get("idempotency_key") or derived_key

    existing = session.scalar(select(Lead).where(Lead.idempotency_key == key))
    if existing is not None:
        return existing, False

    intent = LeadIntent(payload.get("intent", LeadIntent.REQUEST.value))
    reference = next_ref_code(session)
    message = compose_message(
        company,
        branch,
        offer,
        reference=reference,
        custom=payload.get("message"),
        requested_at=payload.get("requested_at"),
        params=payload.get("params"),
    )

    lead = Lead(
        id=new_id("lead"),
        ref_code=reference,
        company_id=company.id,
        branch_id=branch.id,
        offer_id=offer.id if offer else None,
        category_id=offer.category_id if offer else company.primary_category_id,
        intent=intent,
        status=LeadStatus.SUBMITTED,
        customer_name=payload.get("customer_name"),
        customer_phone=phone,
        customer_phone_hash=phone_hash,
        message=payload.get("message"),
        prefilled_message=message,
        requested_at=payload.get("requested_at"),
        params={**(payload.get("params") or {}), "session_ref": session_ref},
        consent_id=consent.id,
        campaign_id=payload.get("campaign_id"),
        utm=(payload.get("utm") or None) and dict(payload["utm"]),
        channel=payload.get("channel") or intent.value,
        idempotency_key=key,
        submitted_at=utcnow(),
    )
    session.add(lead)
    session.flush()

    event = funnel_service.record_event(
        session,
        EventType.LEAD_SUBMITTED,
        company_id=company.id,
        branch_id=branch.id,
        offer_id=offer.id if offer else None,
        lead=lead,
        actor_kind=ActorKind.USER if phone else ActorKind.ANONYMOUS,
        actor_ref=actor_ref,
        session_ref=session_ref,
        source=payload.get("source") or "card",
        campaign_id=lead.campaign_id,
        utm=lead.utm,
        consent=consent,
        evidence={"ref": reference, "intent": intent.value},
    )
    lead.source_event_id = event.event.id

    funnel_service.resolve_attribution(session, lead, window_days=7)
    session.flush()
    return lead, True


# --------------------------------------------------------------------------- #
# Partner-side CRM
# --------------------------------------------------------------------------- #
def lead_by_ref(session: Session, ref: str) -> Lead | None:
    return session.scalar(select(Lead).where(or_(Lead.ref_code == ref, Lead.id == ref)))


def assert_partner_scope(partner: PartnerUser, lead: Lead) -> None:
    if partner.company_id and partner.company_id != lead.company_id:
        raise PermissionError("esta solicitud pertenece a otra empresa")


def change_status(
    session: Session,
    lead: Lead,
    *,
    status: LeadStatus,
    partner: PartnerUser,
    note: str | None = None,
    rejection_reason_es: str | None = None,
    requested_when: str | None = None,
) -> Lead:
    if status not in ALLOWED_TRANSITIONS.get(lead.status, set()):
        raise ValueError(
            f"transición no permitida: {lead.status.value} → {status.value}. "
            f"Permitidas: {sorted(s.value for s in ALLOWED_TRANSITIONS.get(lead.status, set()))}"
        )

    lead.status = status
    lead.decided_at = utcnow()
    lead.decided_by = partner.id
    if note:
        lead.partner_note = note
    if rejection_reason_es:
        lead.rejection_reason_es = rejection_reason_es
    if requested_when:
        lead.requested_at = requested_when

    event_type = _STATUS_EVENT.get(status)
    if event_type:
        funnel_service.record_event(
            session,
            event_type,
            company_id=lead.company_id,
            branch_id=lead.branch_id,
            offer_id=lead.offer_id,
            lead=lead,
            actor_kind=ActorKind.PARTNER,
            actor_ref=partner.id,
            source="partner_cabinet",
            evidence={"ref": lead.ref_code, "note": note},
        )
    session.flush()
    return lead


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #
def serialize_lead(session: Session, lead: Lead, *, include_contact: bool = True) -> dict[str, Any]:
    company = session.get(Company, lead.company_id)
    branch = session.get(Branch, lead.branch_id) if lead.branch_id else None
    offer = session.get(Offer, lead.offer_id) if lead.offer_id else None
    attribution = next((a for a in lead.attributions if a.is_primary), None)

    payload: dict[str, Any] = {
        "id": lead.id,
        "ref_code": lead.ref_code,
        "status": lead.status.value,
        "intent": lead.intent.value,
        "submitted_at": _iso(lead.submitted_at),
        "decided_at": _iso(lead.decided_at),
        "company": {"slug": company.slug, "display_name": company.display_name} if company else None,
        "branch": {"id": branch.id, "name_es": branch.name_es} if branch else None,
        "offer": {"id": offer.id, "title_es": offer.title_es} if offer else None,
        "requested_at": lead.requested_at,
        "message": lead.message,
        "prefilled_message": lead.prefilled_message,
        "params": lead.params or {},
        "attribution": (
            {
                "channel": attribution.channel,
                "campaign_id": attribution.campaign_id,
                "method": attribution.method,
                "confidence": attribution.confidence,
                "window_days": attribution.window_days,
                "disputed": attribution.disputed,
            }
            if attribution
            else None
        ),
        "confirmed_amount_pyg": lead.confirmed_amount_pyg,
        "confirmed_amount_display": format_pyg(lead.confirmed_amount_pyg)
        if lead.confirmed_amount_pyg is not None
        else None,
        "confirmed_at": _iso(lead.confirmed_at),
        "proof_ref": lead.proof_ref,
        "partner_note": lead.partner_note,
        "rejection_reason_es": lead.rejection_reason_es,
        "allowed_transitions": sorted(s.value for s in ALLOWED_TRANSITIONS.get(lead.status, set())),
        "settlements": [
            {
                "id": s.id,
                "status": s.status.value,
                "basis_amount_display": format_pyg(s.basis_amount_pyg),
                "commission_display": format_pyg(s.commission_amount_pyg),
                "contribution_margin_display": format_pyg(s.contribution_margin_pyg),
            }
            for s in lead.settlements
        ],
    }
    if include_contact:
        payload["customer_name"] = lead.customer_name
        payload["customer_phone"] = lead.customer_phone
    return payload
