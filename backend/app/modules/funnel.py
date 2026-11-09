"""Funnel event ledger (§07, §13.4).

Responsibilities
----------------
* append-only recording of every funnel event with unambiguous id, type,
  source, campaign, consent, timestamp and a causal link to a lead/contract;
* **idempotency** — the same business fact can never be written twice, so one
  purchase can never generate two commissions;
* de-duplication hashes for analytics (repeated impressions in a short window);
* attribution resolution with a short window and the possibility to dispute;
* dashboards that always show *what an event proves and what it does not*
  (``app/core/funnel.py`` is the single wording source).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.funnel import FUNNEL, STAGES, EventType
from app.core.ids import new_id, stable_hash, utcnow
from app.domain.models import (
    ActorKind,
    Company,
    Consent,
    FunnelEvent,
    Lead,
    LeadAttribution,
    LeadStatus,
)

#: awareness events are de-duplicated inside a 5-minute bucket, commercial
#: events inside a whole day — they must not be collapsed across days.
_SHORT_BUCKET_STAGES = {"awareness", "interest", "contact"}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _bucket(spec_stage: str, when: datetime) -> str:
    when = _aware(when) or utcnow()
    if spec_stage in _SHORT_BUCKET_STAGES:
        minute = (when.minute // 5) * 5
        return when.strftime(f"%Y%m%d%H{minute:02d}")
    return when.strftime("%Y%m%d")


@dataclass(slots=True)
class EventResult:
    event: FunnelEvent
    created: bool
    deduplicated: bool = False


def build_idempotency_key(
    event_type: str | EventType,
    *,
    company_id: str | None = None,
    branch_id: str | None = None,
    offer_id: str | None = None,
    lead_id: str | None = None,
    session_ref: str | None = None,
    actor_ref: str | None = None,
    campaign_id: str | None = None,
    occurred_at: datetime | None = None,
    extra: str | None = None,
) -> str:
    """Derive a server-side idempotency key from business coordinates.

    Never derived from free client input alone (§07: de-duplication must be
    dependable), but a client-supplied key is accepted when it is stable.
    """
    code = event_type.value if isinstance(event_type, EventType) else event_type
    try:
        stage = FUNNEL[EventType(code)].stage
    except (KeyError, ValueError):
        stage = "sale"
    when = _aware(occurred_at) or utcnow()
    return stable_hash(
        code,
        company_id,
        branch_id,
        offer_id,
        lead_id,
        session_ref,
        actor_ref,
        campaign_id,
        extra,
        _bucket(stage, when),
    )


def record_event(
    session: Session,
    event_type: EventType | str,
    *,
    company_id: str | None = None,
    branch_id: str | None = None,
    offer_id: str | None = None,
    lead: Lead | None = None,
    contract_id: str | None = None,
    actor_kind: ActorKind = ActorKind.ANONYMOUS,
    actor_ref: str | None = None,
    session_ref: str | None = None,
    source: str | None = None,
    campaign_id: str | None = None,
    utm: dict | None = None,
    consent: Consent | None = None,
    amount_pyg: int | None = None,
    evidence: dict | None = None,
    idempotency_key: str | None = None,
    occurred_at: datetime | None = None,
    note: str | None = None,
    commit: bool = False,
) -> EventResult:
    """Record one funnel event idempotently.

    Returns the stored event and whether it was created by this call. Repeated
    calls with the same business coordinates return the original row instead of
    inserting a duplicate.
    """
    code = event_type.value if isinstance(event_type, EventType) else str(event_type)
    if code not in {e.value for e in EventType}:
        raise ValueError(f"unknown event_type: {code}")

    spec = FUNNEL[EventType(code)]
    occurred_at = _aware(occurred_at) or utcnow()

    if spec.requires_consent and (consent is None or not consent.is_valid):
        # §13.4: consent precedes transferring contacts to the seller.
        raise PermissionError("consent is required before recording this event")

    key = idempotency_key or build_idempotency_key(
        code,
        company_id=company_id,
        branch_id=branch_id,
        offer_id=offer_id,
        lead_id=lead.id if lead else None,
        session_ref=session_ref,
        actor_ref=actor_ref,
        campaign_id=campaign_id,
        occurred_at=occurred_at,
        extra=(evidence or {}).get("ref") if isinstance(evidence, dict) else None,
    )

    existing = session.scalar(select(FunnelEvent).where(FunnelEvent.idempotency_key == key))
    if existing is not None:
        return EventResult(event=existing, created=False, deduplicated=True)

    event = FunnelEvent(
        id=new_id("event"),
        event_type=code,
        occurred_at=occurred_at,
        company_id=company_id,
        branch_id=branch_id,
        offer_id=offer_id,
        lead_id=lead.id if lead else None,
        contract_id=contract_id,
        actor_kind=actor_kind,
        actor_ref=actor_ref,
        session_ref=session_ref,
        source=source,
        campaign_id=campaign_id,
        utm=utm,
        consent_id=consent.id if consent else None,
        amount_pyg=amount_pyg,
        evidence=evidence,
        idempotency_key=key,
        dedupe_hash=stable_hash(code, company_id, session_ref, actor_ref, _bucket(spec.stage, occurred_at)),
        note=note,
    )
    session.add(event)
    if commit:
        session.commit()
        session.refresh(event)
    else:
        session.flush()
    return EventResult(event=event, created=True)


# --------------------------------------------------------------------------- #
# Attribution (§07)
# --------------------------------------------------------------------------- #
_TOUCH_PRIORITY = {
    EventType.WHATSAPP_CLICK.value: 60,
    EventType.CALL_CLICK.value: 60,
    EventType.SITE_CLICK.value: 50,
    EventType.ROUTE_CLICK.value: 45,
    EventType.CARD_OPEN.value: 30,
    EventType.SEARCH_RESULT.value: 10,
    EventType.VIEW.value: 5,
}


def resolve_attribution(
    session: Session,
    lead: Lead,
    *,
    window_days: int = 7,
    commit: bool = False,
) -> LeadAttribution:
    """Attach the primary attribution to a lead: last meaningful touch inside
    a short window, with evidence event ids and an explicit method.

    A disputed attribution can be flagged later; nothing here claims causality
    of an advertising campaign by itself (§07).
    """
    submitted = _aware(lead.submitted_at) or utcnow()
    since = submitted - timedelta(days=max(window_days, 0))

    stmt = (
        select(FunnelEvent)
        .where(
            FunnelEvent.company_id == lead.company_id,
            FunnelEvent.occurred_at >= since,
            FunnelEvent.occurred_at <= submitted,
            FunnelEvent.event_type.in_(tuple(_TOUCH_PRIORITY)),
        )
        .order_by(FunnelEvent.occurred_at.desc())
        .limit(50)
    )
    candidates = list(session.scalars(stmt))

    lead_session = (lead.params or {}).get("session_ref")
    same_session = [e for e in candidates if lead_session and e.session_ref == lead_session]
    pool = same_session or candidates
    best = max(
        pool,
        key=lambda e: (_TOUCH_PRIORITY.get(e.event_type, 0), _aware(e.occurred_at) or utcnow()),
        default=None,
    )

    if best is None:
        channel = lead.channel or "direct"
        method = "direct"
        confidence = "low"
        evidence: list[str] = []
        campaign = lead.campaign_id
    else:
        channel = best.source or (best.utm or {}).get("source") or best.event_type
        method = "utm" if (best.utm or best.campaign_id) else "manual_reconciliation"
        confidence = "high" if same_session else "medium"
        evidence = [e.id for e in pool[:5]]
        campaign = best.campaign_id or lead.campaign_id

    attribution = LeadAttribution(
        id=new_id("attribution"),
        lead_id=lead.id,
        channel=channel,
        campaign_id=campaign,
        method=method,
        window_days=window_days,
        is_primary=True,
        confidence=confidence,
        evidence_event_ids=evidence,
    )
    session.add(attribution)
    if commit:
        session.commit()
        session.refresh(attribution)
    else:
        session.flush()
    return attribution


# --------------------------------------------------------------------------- #
# Dashboards
# --------------------------------------------------------------------------- #
def _filter_window(stmt: Select, since: datetime | None, until: datetime | None) -> Select:
    if since:
        stmt = stmt.where(FunnelEvent.occurred_at >= _aware(since))
    if until:
        stmt = stmt.where(FunnelEvent.occurred_at <= _aware(until))
    return stmt


def funnel_summary(
    session: Session,
    *,
    company_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict:
    """Counts by event and by stage, plus lead lifecycle counters.

    The response always carries the wording of what each event proves and what
    it does not prove, so no report can silently upgrade a click into a sale.
    """
    base = select(FunnelEvent.event_type, func.count(FunnelEvent.id)).group_by(
        FunnelEvent.event_type
    )
    if company_id:
        base = base.where(FunnelEvent.company_id == company_id)
    base = _filter_window(base, since, until)
    counts = {row[0]: int(row[1]) for row in session.execute(base).all()}

    leads_stmt = select(Lead.status, func.count(Lead.id)).group_by(Lead.status)
    if company_id:
        leads_stmt = leads_stmt.where(Lead.company_id == company_id)
    if since:
        leads_stmt = leads_stmt.where(Lead.submitted_at >= _aware(since))
    if until:
        leads_stmt = leads_stmt.where(Lead.submitted_at <= _aware(until))
    lead_counts = {row[0]: int(row[1]) for row in session.execute(leads_stmt).all()}

    submitted = lead_counts.get(LeadStatus.SUBMITTED.value, 0) + sum(
        lead_counts.get(s.value, 0)
        for s in (
            LeadStatus.ACCEPTED,
            LeadStatus.BOOKED,
            LeadStatus.VISIT_DONE,
            LeadStatus.SALE_CONFIRMED,
            LeadStatus.REJECTED,
            LeadStatus.CANCELLED,
        )
    )
    accepted = sum(
        lead_counts.get(s.value, 0)
        for s in (
            LeadStatus.ACCEPTED,
            LeadStatus.BOOKED,
            LeadStatus.VISIT_DONE,
            LeadStatus.SALE_CONFIRMED,
        )
    )
    sales = lead_counts.get(LeadStatus.SALE_CONFIRMED.value, 0)

    def rate(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    events_payload = []
    for event_type in EventType:
        spec = FUNNEL[event_type]
        events_payload.append(
            {
                "code": event_type.value,
                "stage": spec.stage,
                "count": counts.get(event_type.value, 0),
                "proves_es": spec.proves,
                "does_not_prove_es": spec.does_not_prove,
                "commissionable": spec.commissionable,
            }
        )

    stages_payload = []
    for stage in STAGES:
        total = sum(
            counts.get(spec.code.value, 0) for spec in FUNNEL.values() if spec.stage == stage
        )
        stages_payload.append({"code": stage, "count": total})

    return {
        "company_id": company_id,
        "since": since.isoformat() if since else None,
        "until": until.isoformat() if until else None,
        "events": events_payload,
        "stages": stages_payload,
        "leads_by_status": lead_counts,
        "conversion": {
            "card_open_to_contact": rate(
                counts.get(EventType.WHATSAPP_CLICK.value, 0)
                + counts.get(EventType.CALL_CLICK.value, 0),
                counts.get(EventType.CARD_OPEN.value, 0),
            ),
            "contact_to_lead": rate(
                counts.get(EventType.LEAD_SUBMITTED.value, 0),
                counts.get(EventType.WHATSAPP_CLICK.value, 0)
                + counts.get(EventType.CALL_CLICK.value, 0),
            ),
            "lead_acceptance_rate": rate(accepted, submitted),
            "lead_to_sale": rate(sales, submitted),
        },
        "warning_es": (
            "Impresión, clic o WhatsApp abierto NO equivalen a un cliente traído "
            "ni a una venta confirmada. Solo el contrato define qué se paga."
        ),
    }


def event_stream(
    session: Session,
    *,
    company_id: str | None = None,
    event_type: str | None = None,
    lead_id: str | None = None,
    limit: int = 100,
) -> list[FunnelEvent]:
    stmt = select(FunnelEvent).order_by(FunnelEvent.occurred_at.desc(), FunnelEvent.id.desc())
    if company_id:
        stmt = stmt.where(FunnelEvent.company_id == company_id)
    if event_type:
        stmt = stmt.where(FunnelEvent.event_type == event_type)
    if lead_id:
        stmt = stmt.where(FunnelEvent.lead_id == lead_id)
    return list(session.scalars(stmt.limit(min(limit, 500))).all())


def company_by_slug(session: Session, slug: str) -> Company | None:
    return session.scalar(select(Company).where(Company.slug == slug))
