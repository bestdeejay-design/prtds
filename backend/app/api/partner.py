"""Partner cabinet API — manual reconciliation of requests and results (§07).

The cabinet is deliberately small: it exists so that a real owner or manager in
Paraguay can confirm what actually happened, without a POS integration. Feed/POS
/API reconciliation for large chains is a later step.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import PartnerUserDep, DbSession
from app.core.ids import utcnow
from app.core.security import hash_token
from app.domain.models import (
    Company,
    Contract,
    Lead,
    LeadStatus,
    PartnerUser,
    Settlement,
    SettlementStatus,
)
from app.domain.schemas import LeadDecision, SaleConfirm
from app.modules import catalog, commerce, funnel as funnel_service, leads as leads_service

router = APIRouter(prefix="/api/partner", tags=["partner"])


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"fecha inválida: {value}") from exc


def _scoped(session, partner: PartnerUser, stmt):
    if partner.company_id:
        stmt = stmt.where(Lead.company_id == partner.company_id)
    return stmt


@router.get("/me")
def me(session: DbSession, partner: PartnerUserDep) -> dict[str, Any]:
    company = session.get(Company, partner.company_id) if partner.company_id else None
    contract = session.get(Contract, partner.contract_id) if partner.contract_id else None

    partner.last_seen_at = utcnow()
    session.commit()

    return {
        "id": partner.id,
        "full_name": partner.full_name,
        "role": partner.role.value,
        "company": {"slug": company.slug, "display_name": company.display_name} if company else None,
        "scope": "single_company" if partner.company_id else "all_companies",
        "contract": commerce.serialize_contract(session, contract) if contract else None,
        "token_fingerprint": hash_token(partner.token_hash)[:8],
        "note_es": (
            "Los datos que ves aquí son solicitudes entregadas con consentimiento del cliente. "
            "Confirmar un resultado falso distorsiona la atribución y las liquidaciones."
        ),
    }


@router.get("/leads")
def list_leads(
    session: DbSession,
    partner: PartnerUserDep,
    status: LeadStatus | None = Query(default=None),
    q: str | None = Query(default=None, max_length=120),
    since: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    stmt = select(Lead).order_by(Lead.submitted_at.desc())
    stmt = _scoped(session, partner, stmt)
    if status:
        stmt = stmt.where(Lead.status == status)
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            Lead.ref_code.ilike(pattern)
            | Lead.customer_name.ilike(pattern)
            | Lead.customer_phone.ilike(pattern)
        )
    since_dt = _parse_date(since)
    if since_dt:
        stmt = stmt.where(Lead.submitted_at >= since_dt)

    rows = list(session.scalars(stmt.limit(limit)).all())
    counts = dict(
        session.execute(
            _scoped(
                session,
                partner,
                select(Lead.status, func.count(Lead.id)).group_by(Lead.status),
            )
        ).all()
    )
    return {
        "total": len(rows),
        "counts_by_status": {
            (key.value if hasattr(key, "value") else str(key)): int(value)
            for key, value in counts.items()
        },
        "leads": [leads_service.serialize_lead(session, lead) for lead in rows],
    }


@router.get("/leads/{ref}")
def get_lead(session: DbSession, partner: PartnerUserDep, ref: str) -> dict[str, Any]:
    lead = leads_service.lead_by_ref(session, ref)
    if lead is None:
        raise HTTPException(status_code=404, detail="Solicitud inexistente.")
    try:
        leads_service.assert_partner_scope(partner, lead)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    payload = leads_service.serialize_lead(session, lead)
    payload["events"] = [
        {
            "event_type": event.event_type,
            "occurred_at": event.occurred_at.isoformat(),
            "actor_kind": event.actor_kind.value,
            "source": event.source,
            "amount_pyg": event.amount_pyg,
        }
        for event in funnel_service.event_stream(session, lead_id=lead.id, limit=50)
    ]
    return payload


@router.post("/leads/{ref}/decision")
def decide(
    session: DbSession, partner: PartnerUserDep, ref: str, payload: LeadDecision
) -> dict[str, Any]:
    lead = leads_service.lead_by_ref(session, ref)
    if lead is None:
        raise HTTPException(status_code=404, detail="Solicitud inexistente.")
    try:
        leads_service.assert_partner_scope(partner, lead)
        leads_service.change_status(
            session,
            lead,
            status=payload.status,
            partner=partner,
            note=payload.note,
            rejection_reason_es=payload.rejection_reason_es,
            requested_when=payload.requested_when,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session.commit()
    return leads_service.serialize_lead(session, lead)


@router.post("/leads/{ref}/sale")
def confirm_sale(
    session: DbSession, partner: PartnerUserDep, ref: str, payload: SaleConfirm
) -> dict[str, Any]:
    lead = leads_service.lead_by_ref(session, ref)
    if lead is None:
        raise HTTPException(status_code=404, detail="Solicitud inexistente.")
    try:
        leads_service.assert_partner_scope(partner, lead)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    occurred_at = payload.occurred_at or utcnow()
    try:
        event, settlement = commerce.confirm_sale(
            session,
            lead,
            amount_pyg=payload.amount_pyg,
            partner=partner,
            proof_ref=payload.proof_ref,
            occurred_at=occurred_at,
            note=payload.note,
            is_repeat=payload.is_repeat,
            idempotency_key=payload.idempotency_key,
        )
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session.commit()
    return {
        "lead": leads_service.serialize_lead(session, lead),
        "event": {
            "id": event.id,
            "event_type": event.event_type,
            "amount_pyg": event.amount_pyg,
            "occurred_at": event.occurred_at.isoformat(),
        },
        "settlement": commerce.serialize_settlement(session, settlement),
        "explanation_es": (
            "El importe confirmado es la venta del comercio (GMV). "
            "El ingreso de PRTDS es únicamente la comisión calculada según el contrato."
        ),
    }


@router.get("/settlements")
def list_settlements(
    session: DbSession,
    partner: PartnerUserDep,
    status: SettlementStatus | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    stmt = select(Settlement).order_by(Settlement.created_at.desc())
    if partner.company_id:
        stmt = stmt.where(Settlement.company_id == partner.company_id)
    if status:
        stmt = stmt.where(Settlement.status == status)
    rows = list(session.scalars(stmt.limit(limit)).all())
    return {
        "total": len(rows),
        "settlements": [commerce.serialize_settlement(session, row) for row in rows],
    }


@router.get("/dashboard")
def dashboard(
    session: DbSession,
    partner: PartnerUserDep,
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
    spend_pyg: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    since_dt = _parse_date(since)
    until_dt = _parse_date(until)

    summary = funnel_service.funnel_summary(
        session, company_id=partner.company_id, since=since_dt, until=until_dt
    )
    economics = commerce.revenue_summary(
        session,
        company_id=partner.company_id,
        since=since_dt,
        until=until_dt,
        spend_pyg=spend_pyg,
    )
    company = session.get(Company, partner.company_id) if partner.company_id else None
    card = catalog.serialize_card(session, company) if company else None

    return {
        "funnel": summary,
        "economics": economics,
        "card_health": (
            {
                "publication_status": card["publication_status"],
                "verification_level": card["verification_level"],
                "branches": len(card["branches"]),
                "offers": len(card["offers"]),
                "stale_offers": card["data_freshness"]["stale_offers"],
                "last_observed_at": card["data_freshness"]["last_observed_at"],
            }
            if card
            else None
        ),
        "todo_es": [
            "Confirmar o rechazar las solicitudes nuevas del día.",
            "Cargar el importe y el comprobante de las ventas efectivamente realizadas.",
            "Revisar las liquidaciones marcadas con margen no positivo.",
        ],
    }
