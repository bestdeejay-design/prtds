"""Commerce module — the only place where money is calculated (§10).

Principles encoded here
-----------------------
* PRTDS revenue is its **commission / service fee**, never the seller's GMV.
  A 5% contract on a 100 000 G. basket yields 5 000 G., not 100 000 G.
* Revenue appears only with a **contractual basis + a confirmed event + a
  fulfilled service**. A click never creates a commission (§06).
* One confirmed result produces exactly one settlement: the idempotency key is
  derived from the event id and the column is UNIQUE (§13.4).
* Hard unit-economics rule: contribution margin must be > 0. A non-positive
  margin is flagged ``flagged_negative_cm`` and never silently approved.
* Caps (per event and per period) and postpaid terms come from the contract,
  not from a global platform tariff; 3–7% remains a negotiation guideline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.funnel import EventType
from app.core.ids import new_id, stable_hash, utcnow
from app.core.money import ContributionMargin, apply_bps, bps_to_pct, format_pyg
from app.domain.models import (
    ActorKind,
    BillingModel,
    CapPeriod,
    Category,
    CommissionRule,
    Company,
    Contract,
    ContractStatus,
    FunnelEvent,
    Lead,
    LeadStatus,
    PartnerUser,
    Settlement,
    SettlementStatus,
)
from app.modules import funnel as funnel_service

COMMISSIONABLE_EVENTS = (
    EventType.SALE_CONFIRMED,
    EventType.RECEIPT_MATCHED,
    EventType.REPEAT_PURCHASE,
)

#: statuses that count as PRTDS revenue (accrued or better)
REVENUE_STATUSES = (
    SettlementStatus.PENDING,
    SettlementStatus.APPROVED,
    SettlementStatus.PAID,
)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    value = _aware(value)
    return value.isoformat() if value else None


# --------------------------------------------------------------------------- #
# Contract & rule resolution
# --------------------------------------------------------------------------- #
def active_contract(session: Session, company_id: str, when: datetime | None = None) -> Contract | None:
    when = _aware(when) or utcnow()
    contracts = list(
        session.scalars(
            select(Contract).where(
                Contract.company_id == company_id, Contract.status == ContractStatus.ACTIVE
            )
        ).all()
    )
    valid = [c for c in contracts if c.is_active_at(when)]
    if not valid:
        return None
    # the most recently signed active contract wins; deterministic tie-break by id
    valid.sort(key=lambda c: (_aware(c.signed_at) or datetime.min.replace(tzinfo=timezone.utc), c.id))
    return valid[-1]


#: a repeat purchase is still a confirmed sale: unless the partner negotiated a
#: dedicated rule for ``repeat_purchase``, it inherits the ``sale_confirmed`` rule.
RULE_FALLBACK = {EventType.REPEAT_PURCHASE.value: EventType.SALE_CONFIRMED.value}


def _pick_rule(
    session: Session, company: Company, event_type: str, company_category_ids: list[str]
) -> CommissionRule | None:
    stmt = (
        select(CommissionRule)
        .where(CommissionRule.is_active.is_(True))
        .where(CommissionRule.applies_to == event_type)
        .order_by(CommissionRule.priority.asc(), CommissionRule.created_at.desc())
    )
    candidates = list(session.scalars(stmt).all())

    for rule in candidates:
        if rule.scope == "company" and rule.company_id == company.id:
            return rule
    for rule in candidates:
        if rule.scope == "category" and rule.category_id in company_category_ids:
            return rule
    for rule in candidates:
        if rule.scope == "global":
            return rule
    return None


def resolve_rule(
    session: Session,
    *,
    company: Company,
    event_type: str,
    contract: Contract | None = None,
) -> CommissionRule | None:
    """contract's own rule > company-scoped > category-scoped > global.

    Priority is explicit and deterministic; nothing is inferred at runtime.
    """
    if contract is not None and contract.commission_rule is not None:
        rule = contract.commission_rule
        if rule.is_active and rule.applies_to == event_type:
            return rule
        fallback = RULE_FALLBACK.get(event_type)
        if fallback and rule.is_active and rule.applies_to == fallback:
            return rule

    company_category_ids = category_ids_for_company(session, company)
    rule = _pick_rule(session, company, event_type, company_category_ids)
    if rule is None:
        fallback = RULE_FALLBACK.get(event_type)
        if fallback:
            rule = _pick_rule(session, company, fallback, company_category_ids)
    return rule


def period_key(when: datetime, cap_period: CapPeriod) -> str | None:
    when = _aware(when) or utcnow()
    if cap_period is CapPeriod.NONE:
        return None
    if cap_period is CapPeriod.DAY:
        return when.strftime("%Y-%m-%d")
    if cap_period is CapPeriod.WEEK:
        iso = when.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return when.strftime("%Y-%m")


def cap_remaining(session: Session, contract: Contract, when: datetime) -> int | None:
    """Money still available under the contractual cap for the period."""
    if not contract.cap_amount_pyg or contract.cap_period is CapPeriod.NONE:
        return None
    key = period_key(when, contract.cap_period)
    if key is None:
        return None
    used = session.scalar(
        select(func.coalesce(func.sum(Settlement.commission_amount_pyg), 0)).where(
            Settlement.contract_id == contract.id,
            Settlement.period_key == key,
            Settlement.status.not_in(
                [SettlementStatus.VOID, SettlementStatus.NO_CONTRACT_BASIS]
            ),
        )
    )
    return max(int(contract.cap_amount_pyg) - int(used or 0), 0)


# --------------------------------------------------------------------------- #
# Settlement engine
# --------------------------------------------------------------------------- #
def create_settlement(
    session: Session,
    *,
    event: FunnelEvent,
    company: Company,
    lead: Lead | None = None,
    basis_amount_pyg: int = 0,
    occurred_at: datetime | None = None,
    proof_ref: str | None = None,
    idempotency_key: str | None = None,
) -> Settlement:
    """Create (or return) the commission basis for one confirmed result.

    Idempotent by event id: replaying the same confirmation cannot produce a
    second commission.
    """
    occurred_at = _aware(occurred_at) or _aware(event.occurred_at) or utcnow()
    key = idempotency_key or stable_hash("settlement", event.id)

    existing = session.scalar(select(Settlement).where(Settlement.idempotency_key == key))
    if existing is not None:
        return existing

    contract = active_contract(session, company.id, occurred_at)
    settlement = Settlement(
        id=new_id("settlement"),
        idempotency_key=key,
        lead_id=lead.id if lead else None,
        event_id=event.id,
        contract_id=contract.id if contract else None,
        company_id=company.id,
        basis_kind=event.event_type,
        basis_amount_pyg=int(basis_amount_pyg or 0),
        currency="PYG",
        proof_ref=proof_ref,
        period_key=None,
    )
    session.add(settlement)

    if contract is None:
        settlement.status = SettlementStatus.NO_CONTRACT_BASIS
        settlement.status_reason_es = (
            "Resultado confirmado sin contrato activo: no surge comisión. "
            "La presencia en el catálogo es gratuita y no se cobra «por clic»."
        )
        settlement.commission_amount_pyg = 0
        settlement.contribution_margin_pyg = 0
        session.flush()
        return settlement

    rule = resolve_rule(session, company=company, event_type=event.event_type, contract=contract)
    if rule is None:
        settlement.status = SettlementStatus.NO_CONTRACT_BASIS
        settlement.status_reason_es = (
            "Contrato activo sin regla de comisión aplicable a este evento."
        )
        settlement.commission_amount_pyg = 0
        session.flush()
        return settlement

    settlement.rule_id = rule.id
    settlement.rate_bps = int(rule.rate_bps or 0)
    settlement.fixed_amount_pyg = int(rule.fixed_amount_pyg or 0)
    settlement.period_key = period_key(occurred_at, contract.cap_period)

    commission = apply_bps(settlement.basis_amount_pyg, rule.rate_bps) + int(rule.fixed_amount_pyg)

    if rule.min_amount_pyg and settlement.basis_amount_pyg < int(rule.min_amount_pyg):
        commission = 0
        settlement.status_reason_es = (
            f"Importe por debajo del mínimo contractual ({format_pyg(rule.min_amount_pyg)})."
        )

    if rule.max_amount_per_event_pyg and commission > int(rule.max_amount_per_event_pyg):
        commission = int(rule.max_amount_per_event_pyg)
        settlement.cap_applied = True
        settlement.status_reason_es = "Tope por evento aplicado."

    remaining = cap_remaining(session, contract, occurred_at)
    if remaining is not None and commission > remaining:
        commission = remaining
        settlement.cap_applied = True
        settlement.status_reason_es = (
            (settlement.status_reason_es or "") + " Tope de período alcanzado."
        ).strip()

    settlement.direct_costs_pyg = int(contract.direct_costs_pyg or 0)
    margin = ContributionMargin(
        commission=commission,
        direct_costs=settlement.direct_costs_pyg,
        prtds_funded_discounts=int(settlement.prtds_funded_discount_pyg or 0),
    )
    settlement.commission_amount_pyg = commission
    settlement.contribution_margin_pyg = margin.total

    if commission == 0 and settlement.status_reason_es and "mínimo" in settlement.status_reason_es:
        settlement.status = SettlementStatus.PENDING
    elif not margin.is_positive:
        settlement.status = SettlementStatus.FLAGGED_NEGATIVE_CM
        settlement.status_reason_es = (
            "Margen de contribución no positivo: la operación no debe escalarse "
            "sin renegociar comisión o costos variables."
        )
    else:
        settlement.status = SettlementStatus.PENDING
        settlement.status_reason_es = settlement.status_reason_es or "Pendiente de conciliación con el socio."

    session.flush()
    return settlement


def confirm_sale(
    session: Session,
    lead: Lead,
    *,
    amount_pyg: int,
    partner: PartnerUser,
    proof_ref: str | None = None,
    occurred_at: datetime | None = None,
    note: str | None = None,
    is_repeat: bool = False,
    idempotency_key: str | None = None,
) -> tuple[FunnelEvent, Settlement]:
    """Register a confirmed commercial result with proof and compute the basis.

    The seller's amount is stored as GMV; PRTDS revenue is computed separately.
    """
    if lead.status is LeadStatus.SALE_CONFIRMED and not is_repeat:
        existing_event = session.scalar(
            select(FunnelEvent).where(
                FunnelEvent.lead_id == lead.id,
                FunnelEvent.event_type == EventType.SALE_CONFIRMED.value,
            )
        )
        existing_settlement = session.scalar(
            select(Settlement).where(Settlement.lead_id == lead.id)
        )
        if existing_event and existing_settlement:
            return existing_event, existing_settlement

    company = session.get(Company, lead.company_id)
    if company is None:  # pragma: no cover - guarded by FK
        raise LookupError("empresa inexistente para la solicitud")

    occurred_at = _aware(occurred_at) or utcnow()
    event_type = EventType.REPEAT_PURCHASE if is_repeat else EventType.SALE_CONFIRMED

    if lead.status not in (LeadStatus.SALE_CONFIRMED,) and event_type is not EventType.REPEAT_PURCHASE:
        allowed = {
            LeadStatus.SUBMITTED,
            LeadStatus.ACCEPTED,
            LeadStatus.BOOKED,
            LeadStatus.VISIT_DONE,
        }
        if lead.status not in allowed:
            raise ValueError(
                f"no se puede confirmar una venta desde el estado {lead.status.value}"
            )

    #: a replayed confirmation (same lead, amount, proof and day) collapses into
    #: one event; a different receipt produces a distinct one.
    derived_key = stable_hash(
        event_type.value,
        lead.id,
        partner.id,
        int(amount_pyg),
        proof_ref or "",
        occurred_at.strftime("%Y%m%d"),
    )

    event_result = funnel_service.record_event(
        session,
        event_type,
        company_id=lead.company_id,
        branch_id=lead.branch_id,
        offer_id=lead.offer_id,
        lead=lead,
        actor_kind=ActorKind.PARTNER,
        actor_ref=partner.id,
        source="partner_cabinet",
        amount_pyg=int(amount_pyg),
        occurred_at=occurred_at,
        idempotency_key=idempotency_key or derived_key,
        evidence={"proof_ref": proof_ref, "note": note, "ref": lead.ref_code},
    )
    event = event_result.event

    settlement = create_settlement(
        session,
        event=event,
        company=company,
        lead=lead,
        basis_amount_pyg=int(amount_pyg),
        occurred_at=occurred_at,
        proof_ref=proof_ref,
    )

    if not is_repeat:
        lead.status = LeadStatus.SALE_CONFIRMED
        lead.confirmed_amount_pyg = int(amount_pyg)
        lead.confirmed_at = occurred_at
        lead.proof_ref = proof_ref
        lead.decided_at = utcnow()
        lead.decided_by = partner.id
        if note:
            lead.partner_note = note

    if settlement.commission_amount_pyg:
        funnel_service.record_event(
            session,
            EventType.SETTLEMENT_CREATED,
            company_id=lead.company_id,
            lead=lead,
            contract_id=settlement.contract_id,
            actor_kind=ActorKind.SYSTEM,
            actor_ref="settlement-engine",
            source="platform",
            amount_pyg=settlement.commission_amount_pyg,
            evidence={"settlement_id": settlement.id, "status": settlement.status.value},
        )

    session.flush()
    return event, settlement


# --------------------------------------------------------------------------- #
# Serialisation & reporting
# --------------------------------------------------------------------------- #
def serialize_settlement(session: Session, settlement: Settlement) -> dict[str, Any]:
    lead = session.get(Lead, settlement.lead_id) if settlement.lead_id else None
    company = session.get(Company, settlement.company_id)
    contract = session.get(Contract, settlement.contract_id) if settlement.contract_id else None
    rule = session.get(CommissionRule, settlement.rule_id) if settlement.rule_id else None

    return {
        "id": settlement.id,
        "status": settlement.status.value,
        "status_reason_es": settlement.status_reason_es,
        "created_at": _iso(settlement.created_at),
        "company": {"slug": company.slug, "display_name": company.display_name} if company else None,
        "lead_ref": lead.ref_code if lead else None,
        "contract_number": contract.number if contract else None,
        "billing_model": contract.billing_model.value if contract else None,
        "rule": (
            {
                "name": rule.name,
                "rate_percent": float(bps_to_pct(rule.rate_bps)),
                "fixed_amount_display": format_pyg(rule.fixed_amount_pyg),
            }
            if rule
            else None
        ),
        "basis_kind": settlement.basis_kind,
        "basis_amount_pyg": settlement.basis_amount_pyg,
        "basis_amount_display": format_pyg(settlement.basis_amount_pyg),
        "rate_bps": settlement.rate_bps,
        "commission_amount_pyg": settlement.commission_amount_pyg,
        "commission_display": format_pyg(settlement.commission_amount_pyg),
        "direct_costs_pyg": settlement.direct_costs_pyg,
        "contribution_margin_pyg": settlement.contribution_margin_pyg,
        "contribution_margin_display": format_pyg(settlement.contribution_margin_pyg),
        "cap_applied": settlement.cap_applied,
        "period_key": settlement.period_key,
        "proof_ref": settlement.proof_ref,
        "note_es": (
            "El importe base es la venta del comercio (GMV); el ingreso de PRTDS es solo la comisión."
        ),
    }


def revenue_summary(
    session: Session,
    *,
    company_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    spend_pyg: int = 0,
) -> dict[str, Any]:
    """PRTDS economics: GMV vs revenue, margin, cost of acquisition.

    Reported the way §14 demands: not database row counts, but new customers,
    repeat sales, PRTDS revenue, contribution margin and acquisition cost.
    """
    stmt = select(Settlement).where(
        Settlement.status.not_in([SettlementStatus.VOID])
    )
    if company_id:
        stmt = stmt.where(Settlement.company_id == company_id)
    if since:
        stmt = stmt.where(Settlement.created_at >= _aware(since))
    if until:
        stmt = stmt.where(Settlement.created_at <= _aware(until))
    settlements = list(session.scalars(stmt).all())

    gmv = sum(s.basis_amount_pyg for s in settlements if s.status is not SettlementStatus.NO_CONTRACT_BASIS)
    revenue = sum(s.commission_amount_pyg for s in settlements if s.status in REVENUE_STATUSES)
    margin_total = sum(
        s.contribution_margin_pyg for s in settlements if s.status in REVENUE_STATUSES
    )
    #: flagged operations are excluded from revenue but their negative margin is
    #: reported explicitly — the rule of §10 must not be hidden by aggregation.
    flagged_margin = sum(
        s.contribution_margin_pyg
        for s in settlements
        if s.status is SettlementStatus.FLAGGED_NEGATIVE_CM
    )
    flagged_commission = sum(
        s.commission_amount_pyg
        for s in settlements
        if s.status is SettlementStatus.FLAGGED_NEGATIVE_CM
    )
    by_status: dict[str, int] = {}
    for s in settlements:
        by_status[s.status.value] = by_status.get(s.status.value, 0) + 1

    new_customers = session.scalar(
        select(func.count(func.distinct(Lead.customer_phone_hash))).where(
            Lead.status == LeadStatus.SALE_CONFIRMED,
            Lead.customer_phone_hash.is_not(None),
            *([Lead.company_id == company_id] if company_id else []),
        )
    )
    repeat_events = session.scalar(
        select(func.count(FunnelEvent.id)).where(
            FunnelEvent.event_type == EventType.REPEAT_PURCHASE.value,
            *([FunnelEvent.company_id == company_id] if company_id else []),
        )
    )
    confirmed_sales = session.scalar(
        select(func.count(FunnelEvent.id)).where(
            FunnelEvent.event_type.in_(
                [EventType.SALE_CONFIRMED.value, EventType.RECEIPT_MATCHED.value]
            ),
            *([FunnelEvent.company_id == company_id] if company_id else []),
        )
    )
    leads_total = session.scalar(
        select(func.count(Lead.id)).where(
            *([Lead.company_id == company_id] if company_id else []),
        )
    )

    return {
        "company_id": company_id,
        "since": _iso(since),
        "until": _iso(until),
        "currency": "PYG",
        "gmv_pyg": int(gmv),
        "gmv_display": format_pyg(int(gmv)),
        "prtds_revenue_pyg": int(revenue),
        "prtds_revenue_display": format_pyg(int(revenue)),
        "contribution_margin_pyg": int(margin_total),
        "contribution_margin_display": format_pyg(int(margin_total)),
        "flagged_negative_margin_pyg": int(flagged_margin),
        "flagged_negative_margin_display": format_pyg(int(flagged_margin)),
        "flagged_commission_pyg": int(flagged_commission),
        "avg_margin_per_operation_pyg": int(margin_total / len([s for s in settlements if s.status in REVENUE_STATUSES]))
        if any(s.status in REVENUE_STATUSES for s in settlements)
        else 0,
        "settlements_by_status": by_status,
        "counters": {
            "leads_total": int(leads_total or 0),
            "confirmed_sales": int(confirmed_sales or 0),
            "repeat_purchases": int(repeat_events or 0),
            "new_customers_with_phone": int(new_customers or 0),
        },
        "acquisition": {
            "spend_pyg": int(spend_pyg or 0),
            "spend_display": format_pyg(int(spend_pyg or 0)),
            "cost_per_lead_pyg": int(spend_pyg / leads_total) if spend_pyg and leads_total else None,
            "cost_per_confirmed_sale_pyg": int(spend_pyg / confirmed_sales)
            if spend_pyg and confirmed_sales
            else None,
        },
        "alerts": [
            {
                "code": "negative_contribution_margin",
                "count": by_status.get(SettlementStatus.FLAGGED_NEGATIVE_CM.value, 0),
                "message_es": (
                    "Operaciones con margen de contribución no positivo: requieren "
                    "renegociación antes de escalar."
                ),
            },
            {
                "code": "no_contract_basis",
                "count": by_status.get(SettlementStatus.NO_CONTRACT_BASIS.value, 0),
                "message_es": (
                    "Ventas confirmadas sin contrato: ingreso cero. Oportunidad comercial, "
                    "no un cobro pendiente."
                ),
            },
        ],
        "warning_es": "GMV del comercio ≠ ingreso de PRTDS.",
    }


def serialize_contract(session: Session, contract: Contract) -> dict[str, Any]:
    company = session.get(Company, contract.company_id)
    rule = contract.commission_rule
    return {
        "id": contract.id,
        "number": contract.number,
        "status": contract.status.value,
        "billing_model": contract.billing_model.value,
        "counterparty_name": contract.counterparty_name,
        "company": {"slug": company.slug, "display_name": company.display_name} if company else None,
        "signed_at": _iso(contract.signed_at),
        "valid_from": _iso(contract.valid_from),
        "valid_to": _iso(contract.valid_to),
        "attribution_window_days": contract.attribution_window_days,
        "cap_amount_display": format_pyg(contract.cap_amount_pyg) if contract.cap_amount_pyg else None,
        "cap_period": contract.cap_period.value,
        "postpaid": contract.postpaid,
        "direct_costs_pyg": contract.direct_costs_pyg,
        "proof_requirements": contract.proof_requirements or {},
        "rule": (
            {
                "id": rule.id,
                "name": rule.name,
                "applies_to": rule.applies_to,
                "rate_percent": float(bps_to_pct(rule.rate_bps)),
                "fixed_amount_display": format_pyg(rule.fixed_amount_pyg),
                "max_per_event_display": format_pyg(rule.max_amount_per_event_pyg)
                if rule.max_amount_per_event_pyg
                else None,
            }
            if rule
            else None
        ),
        "notes": contract.notes,
    }


def category_ids_for_company(session: Session, company: Company) -> list[str]:
    ids: list[str] = []
    if company.primary_category_id:
        ids.append(company.primary_category_id)
    from app.domain.models import CompanyCategory

    ids.extend(
        cid
        for (cid,) in session.execute(
            select(CompanyCategory.category_id).where(CompanyCategory.company_id == company.id)
        ).all()
    )
    return ids


__all__ = [
    "COMMISSIONABLE_EVENTS",
    "BillingModel",
    "Category",
    "active_contract",
    "cap_remaining",
    "category_ids_for_company",
    "confirm_sale",
    "create_settlement",
    "period_key",
    "resolve_rule",
    "revenue_summary",
    "serialize_contract",
    "serialize_settlement",
]
