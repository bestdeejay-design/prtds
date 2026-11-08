"""Admin API — taxonomy, publication pipeline, contracts and the audit panel.

Everything here is behind ``X-Admin-Token`` in development. In production it must
sit behind real identity with role separation and an audit trail (§13.4).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import AdminDep, DbSession
from app.core.ids import new_id, utcnow
from app.core.money import bps_to_pct, format_pyg, pct_to_bps
from app.core.security import hash_token
from app.domain.models import (
    CommissionRule,
    Company,
    Contract,
    ContractStatus,
    FunnelEvent,
    Lead,
    PartnerRole,
    PartnerUser,
    PublicationStatus,
    Settlement,
    Source,
)
from app.domain.schemas import (
    CategoryCreate,
    CategoryUpdate,
    CommissionRuleIn,
    ContractIn,
    PublicationChange,
    SourceIn,
)
from app.modules import catalog, commerce, funnel as funnel_service

router = APIRouter(prefix="/api/admin", tags=["admin"])

#: publication pipeline (§13.2): staging → validation → moderation → publication
ALLOWED_PUBLICATION_TRANSITIONS: dict[PublicationStatus, set[PublicationStatus]] = {
    PublicationStatus.DRAFT: {PublicationStatus.STAGING, PublicationStatus.ARCHIVED},
    PublicationStatus.STAGING: {PublicationStatus.VALIDATED, PublicationStatus.DRAFT},
    PublicationStatus.VALIDATED: {PublicationStatus.MODERATED, PublicationStatus.STAGING},
    PublicationStatus.MODERATED: {PublicationStatus.PUBLISHED, PublicationStatus.VALIDATED},
    PublicationStatus.PUBLISHED: {PublicationStatus.ARCHIVED, PublicationStatus.MODERATED},
    PublicationStatus.ARCHIVED: {PublicationStatus.STAGING},
}


def _company_or_404(session, slug: str) -> Company:
    company = session.scalar(select(Company).where(Company.slug == slug))
    if company is None:
        raise HTTPException(status_code=404, detail=f"Empresa inexistente: {slug}")
    return company


# --------------------------------------------------------------------------- #
# Categories — the taxonomy is data, not code
# --------------------------------------------------------------------------- #
@router.get("/categories")
def categories(session: DbSession, _admin: AdminDep, include_inactive: bool = True) -> dict[str, Any]:
    return {"categories": catalog.categories_tree(session, include_inactive=include_inactive)}


@router.post("/categories", status_code=201)
def create_category(session: DbSession, _admin: AdminDep, payload: CategoryCreate) -> dict[str, Any]:
    try:
        category = catalog.create_category(session, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return {"id": category.id, "slug": category.slug, "name_es": category.name_es}


@router.patch("/categories/{slug}")
def update_category(
    session: DbSession, _admin: AdminDep, slug: str, payload: CategoryUpdate
) -> dict[str, Any]:
    try:
        category = catalog.update_category(session, slug, payload.model_dump(exclude_unset=True))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return {"id": category.id, "slug": category.slug, "name_es": category.name_es, "is_active": category.is_active}


# --------------------------------------------------------------------------- #
# Publication pipeline
# --------------------------------------------------------------------------- #
@router.post("/companies/{slug}/publication")
def change_publication(
    session: DbSession, _admin: AdminDep, slug: str, payload: PublicationChange
) -> dict[str, Any]:
    company = _company_or_404(session, slug)
    allowed = ALLOWED_PUBLICATION_TRANSITIONS.get(company.publication_status, set())
    if payload.status not in allowed:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Transición no permitida: {company.publication_status.value} → {payload.status.value}. "
                f"Permitidas: {sorted(s.value for s in allowed)}"
            ),
        )

    previous = company.publication_status
    company.publication_status = payload.status
    company.updated_by = "admin"
    if payload.status is PublicationStatus.PUBLISHED and company.published_at is None:
        company.published_at = utcnow()
    session.commit()

    return {
        "slug": company.slug,
        "previous_status": previous.value,
        "status": company.publication_status.value,
        "published_at": company.published_at.isoformat() if company.published_at else None,
        "reason": payload.reason,
        "note_es": (
            "Publicar no equivale a tener una fila en el registro maestro: "
            "la ficha pasó por staging → validación → moderación."
        ),
    }


# --------------------------------------------------------------------------- #
# Contracts and commission rules
# --------------------------------------------------------------------------- #
@router.post("/commission-rules", status_code=201)
def create_rule(session: DbSession, _admin: AdminDep, payload: CommissionRuleIn) -> dict[str, Any]:
    company_id = None
    category_id = None
    if payload.company_slug:
        company_id = _company_or_404(session, payload.company_slug).id
    if payload.category_slug:
        category = catalog.category_by_slug(session, payload.category_slug)
        if category is None:
            raise HTTPException(status_code=404, detail=f"Categoría inexistente: {payload.category_slug}")
        category_id = category.id

    if payload.scope == "company" and not company_id:
        raise HTTPException(status_code=422, detail="scope=company requiere company_slug")
    if payload.scope == "category" and not category_id:
        raise HTTPException(status_code=422, detail="scope=category requiere category_slug")

    rule = CommissionRule(
        id=new_id("rule"),
        name=payload.name,
        scope=payload.scope,
        company_id=company_id,
        category_id=category_id,
        applies_to=payload.applies_to,
        rate_bps=pct_to_bps(payload.rate_percent) if payload.rate_percent is not None else 0,
        fixed_amount_pyg=payload.fixed_amount_pyg,
        min_amount_pyg=payload.min_amount_pyg,
        max_amount_per_event_pyg=payload.max_amount_per_event_pyg,
        priority=payload.priority,
        is_active=payload.is_active,
        notes=payload.notes,
    )
    session.add(rule)
    session.commit()
    return {
        "id": rule.id,
        "name": rule.name,
        "scope": rule.scope,
        "applies_to": rule.applies_to,
        "rate_percent": float(bps_to_pct(rule.rate_bps)),
        "max_per_event_display": format_pyg(rule.max_amount_per_event_pyg)
        if rule.max_amount_per_event_pyg
        else None,
    }


@router.post("/contracts", status_code=201)
def create_contract(session: DbSession, _admin: AdminDep, payload: ContractIn) -> dict[str, Any]:
    company = _company_or_404(session, payload.company_slug)

    rule: CommissionRule | None = None
    if payload.rule_name:
        rule = session.scalar(
            select(CommissionRule).where(
                CommissionRule.name == payload.rule_name, CommissionRule.is_active.is_(True)
            )
        )
        if rule is None:
            raise HTTPException(status_code=404, detail=f"Regla inexistente: {payload.rule_name}")

    existing = session.scalar(select(Contract).where(Contract.number == payload.number))
    if existing is not None:
        raise HTTPException(status_code=422, detail=f"Ya existe el contrato {payload.number}")

    contract = Contract(
        id=new_id("contract"),
        company_id=company.id,
        number=payload.number,
        counterparty_name=payload.counterparty_name,
        contact_name=payload.contact_name,
        status=payload.status,
        billing_model=payload.billing_model,
        commission_rule_id=rule.id if rule else None,
        signed_at=payload.signed_at or utcnow(),
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        attribution_window_days=payload.attribution_window_days,
        cap_amount_pyg=payload.cap_amount_pyg,
        cap_period=payload.cap_period,
        postpaid=payload.postpaid,
        proof_requirements=payload.proof_requirements,
        direct_costs_pyg=payload.direct_costs_pyg,
        notes=payload.notes,
    )
    session.add(contract)
    session.flush()

    created_users = []
    for entry in payload.partner_users or []:
        token = entry.get("token")
        if not token:
            continue
        user = PartnerUser(
            id=new_id("partner_user"),
            contract_id=contract.id,
            company_id=company.id,
            full_name=entry.get("full_name", "Responsable"),
            email=entry.get("email"),
            role=PartnerRole(entry.get("role", PartnerRole.MANAGER.value)),
            token_hash=hash_token(token),
            is_active=True,
        )
        session.add(user)
        created_users.append({"id": user.id, "full_name": user.full_name, "role": user.role.value})

    session.commit()
    body = commerce.serialize_contract(session, contract)
    body["partner_users"] = created_users
    return body


@router.post("/sources", status_code=201)
def create_source(session: DbSession, _admin: AdminDep, payload: SourceIn) -> dict[str, Any]:
    source = Source(
        id=new_id("source"),
        name=payload.name,
        kind=payload.kind,
        url=payload.url,
        retrieved_at=payload.retrieved_at or utcnow(),
        license_note=payload.license_note,
        trusted=payload.trusted,
    )
    session.add(source)
    session.commit()
    return {"id": source.id, "name": source.name, "kind": source.kind}


# --------------------------------------------------------------------------- #
# Audit panel
# --------------------------------------------------------------------------- #
@router.get("/funnel/events")
def events(
    session: DbSession,
    _admin: AdminDep,
    company_slug: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    company_id = _company_or_404(session, company_slug).id if company_slug else None
    rows = funnel_service.event_stream(
        session, company_id=company_id, event_type=event_type, limit=limit
    )
    return {
        "total": len(rows),
        "events": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "occurred_at": event.occurred_at.isoformat(),
                "company_id": event.company_id,
                "lead_id": event.lead_id,
                "source": event.source,
                "campaign_id": event.campaign_id,
                "actor_kind": event.actor_kind.value,
                "amount_pyg": event.amount_pyg,
                "disputed": event.disputed,
                "evidence": event.evidence,
            }
            for event in rows
        ],
    }


@router.get("/stats")
def stats(session: DbSession, _admin: AdminDep) -> dict[str, Any]:
    """The §15 panel: registry rows vs published cards vs money."""
    leads_total = session.scalar(select(func.count(Lead.id))) or 0
    events_total = session.scalar(select(func.count(FunnelEvent.id))) or 0
    settlements_total = session.scalar(select(func.count(Settlement.id))) or 0
    contracts_active = session.scalar(
        select(func.count(Contract.id)).where(Contract.status == ContractStatus.ACTIVE)
    ) or 0

    return {
        "catalog": catalog.registry_vs_public(session),
        "funnel": {"leads_total": int(leads_total), "events_total": int(events_total)},
        "commerce": {
            "settlements_total": int(settlements_total),
            "active_contracts": int(contracts_active),
        },
        "economics": commerce.revenue_summary(session),
    }


@router.get("/settlements")
def settlements(
    session: DbSession,
    _admin: AdminDep,
    status: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    stmt = select(Settlement).order_by(Settlement.created_at.desc())
    if status:
        stmt = stmt.where(Settlement.status == status)
    rows = list(session.scalars(stmt.limit(limit)).all())
    return {
        "total": len(rows),
        "settlements": [commerce.serialize_settlement(session, row) for row in rows],
    }


@router.post("/settlements/{settlement_id}/dispute")
def dispute_settlement(
    session: DbSession, _admin: AdminDep, settlement_id: str, reason: str | None = None
) -> dict[str, Any]:
    settlement = session.get(Settlement, settlement_id)
    if settlement is None:
        raise HTTPException(status_code=404, detail="Liquidación inexistente.")
    from app.domain.models import SettlementStatus

    settlement.status = SettlementStatus.DISPUTED
    settlement.status_reason_es = reason or "En disputa por el comercio."
    session.commit()
    return commerce.serialize_settlement(session, settlement)


@router.post("/reindex")
def reindex(session: DbSession, _admin: AdminDep) -> dict[str, Any]:
    """Rebuild the accent-folded search index for every company."""
    count = catalog.reindex_all(session)
    session.commit()
    return {
        "reindexed_companies": count,
        "note_es": (
            "Índice de búsqueda reconstruido. En producción este trabajo lo hace "
            "tsvector/GIN de PostgreSQL; aquí se mantiene una columna plegada portable."
        ),
    }


@router.post("/reseed")
def reseed(session: DbSession, _admin: AdminDep) -> dict[str, Any]:
    """Dev convenience: rebuild the demo dataset (never used in production)."""
    from app.seed.loader import reseed_all

    report = reseed_all(session)
    session.commit()
    return report
