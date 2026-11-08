"""Public API: search, cards, funnel instrumentation and lead submission."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ClientContext, DbSession
from app.core.funnel import EventType, as_payload as funnel_payload
from app.core.config import settings
from app.core.ids import utcnow
from app.domain.schemas import (
    EventIngest,
    LeadSubmit,
    WhatsAppLinkRequest,
)
from app.modules import catalog, funnel as funnel_service, leads as leads_service

router = APIRouter(prefix="/api", tags=["public"])

#: the public ingest endpoint accepts instrumentation events only; commercial
#: facts must arrive through their own endpoints (leads, partner cabinet) so
#: that consent and proof requirements are enforced server-side.
PUBLIC_EVENTS = {
    EventType.VIEW,
    EventType.SEARCH_RESULT,
    EventType.CARD_OPEN,
    EventType.ROUTE_CLICK,
    EventType.SITE_CLICK,
    EventType.WHATSAPP_CLICK,
    EventType.CALL_CLICK,
}


@router.get("/health")
def health(session: DbSession) -> dict[str, Any]:
    from sqlalchemy import text

    session.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "app_env": settings.app_env,
        "locale": settings.default_locale,
        "currency": settings.default_currency,
        "timezone": settings.timezone_name,
        "server_time_utc": utcnow().isoformat(),
    }


@router.get("/meta/funnel")
def meta_funnel() -> dict[str, Any]:
    """The event dictionary: what each event proves and what it does not."""
    return funnel_payload()


@router.get("/meta/market")
def meta_market() -> dict[str, Any]:
    """Localisation contract for the UI (§02)."""
    return {
        "locale": settings.default_locale,
        "currency": settings.default_currency,
        "currency_symbol": "G.",
        "currency_decimals": 0,
        "timezone": settings.timezone_name,
        "country": settings.default_country,
        "languages": [
            {"code": "es-PY", "name": "Español (Paraguay)", "status": "primary"},
            {"code": "gn", "name": "Guaraní", "status": "reserved"},
            {"code": "ru", "name": "Русский", "status": "internal"},
        ],
        "phone_prefix": "+595",
        "note_es": "Precios en guaraníes sin decimales; barrios y zonas de Paraguay.",
    }


@router.get("/categories")
def list_categories(session: DbSession) -> dict[str, Any]:
    return {"categories": catalog.categories_tree(session)}


@router.get("/facets")
def list_facets(session: DbSession) -> dict[str, Any]:
    return catalog.facets(session)


@router.get("/search")
def search(
    session: DbSession,
    ctx: ClientContext,
    q: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=120),
    barrio: str | None = Query(default=None, max_length=120),
    city: str | None = Query(default=None, max_length=120),
    channel: str | None = Query(default=None, pattern="^(whatsapp|phone|delivery|pickup)$"),
    min_price: int | None = Query(default=None, ge=0),
    max_price: int | None = Query(default=None, ge=0),
    sort: str = Query(default="relevance", pattern="^(relevance|name|recent|price_asc)$"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    campaign_id: str | None = Query(default=None, max_length=64),
    track: bool = Query(default=True),
) -> dict[str, Any]:
    try:
        results = catalog.search(
            session,
            q=q,
            category_slug=category,
            barrio=barrio,
            city=city,
            channel=channel,
            min_price=min_price,
            max_price=max_price,
            sort=sort,
            page=page,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if track:
        shown = catalog.log_search_impressions(
            session,
            results,
            session_ref=ctx["session_ref"],
            actor_ref=ctx["actor_ref"],
            campaign_id=campaign_id,
        )
        session.commit()
        results["tracked_impressions"] = shown
    return results


@router.get("/companies/{slug}")
def company_card(session: DbSession, ctx: ClientContext, slug: str) -> dict[str, Any]:
    company = catalog.published_card(session, slug)
    if company is None:
        raise HTTPException(
            status_code=404,
            detail="Ficha no publicada. Una fila en el registro maestro no es una ficha pública.",
        )
    card = catalog.serialize_card(session, company)

    funnel_service.record_event(
        session,
        EventType.CARD_OPEN,
        company_id=company.id,
        branch_id=company.branches[0].id if company.branches else None,
        actor_ref=ctx["actor_ref"],
        session_ref=ctx["session_ref"],
        source="card",
    )
    session.commit()
    card["tracking"] = {"card_open_recorded": True}
    return card


@router.get("/companies/{slug}/offers")
def company_offers(session: DbSession, slug: str) -> dict[str, Any]:
    company = catalog.published_card(session, slug)
    if company is None:
        raise HTTPException(status_code=404, detail="Ficha no publicada.")
    return {
        "company": {"slug": company.slug, "display_name": company.display_name},
        "offers": [
            catalog.serialize_offer(session, offer)
            for offer in company.offers
            if offer.is_active
        ],
    }


@router.post("/events")
def ingest_event(
    session: DbSession, ctx: ClientContext, payload: EventIngest
) -> dict[str, Any]:
    event_type = EventType(payload.event_type)
    if event_type not in PUBLIC_EVENTS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{event_type.value}' no se acepta por el endpoint público de eventos: "
                "los hechos comerciales (solicitudes, ventas) se registran por sus propios "
                "endpoints con consentimiento y evidencia."
            ),
        )

    company_id = None
    branch_id = payload.branch_id
    offer_id = payload.offer_id
    if payload.company_slug:
        company = catalog.published_card(session, payload.company_slug)
        if company is None:
            raise HTTPException(status_code=404, detail="Ficha no publicada.")
        company_id = company.id

    result = funnel_service.record_event(
        session,
        event_type,
        company_id=company_id,
        branch_id=branch_id,
        offer_id=offer_id,
        actor_ref=ctx["actor_ref"],
        session_ref=ctx["session_ref"],
        source=payload.source,
        campaign_id=payload.campaign_id,
        utm=payload.utm.model_dump(exclude_none=True) if payload.utm else None,
        amount_pyg=payload.amount_pyg,
        idempotency_key=payload.idempotency_key,
    )
    session.commit()

    from app.core.funnel import FUNNEL

    spec = FUNNEL[event_type]
    return {
        "event_id": result.event.id,
        "event_type": result.event.event_type,
        "created": result.created,
        "deduplicated": result.deduplicated,
        "occurred_at": result.event.occurred_at.isoformat(),
        "proves_es": spec.proves,
        "does_not_prove_es": spec.does_not_prove,
    }


@router.post("/whatsapp-link")
def whatsapp_link(session: DbSession, ctx: ClientContext, payload: WhatsAppLinkRequest) -> dict[str, Any]:
    try:
        result = leads_service.build_whatsapp_link(
            session,
            company_slug=payload.company_slug,
            branch_id=payload.branch_id,
            offer_id=payload.offer_id,
            message=payload.message,
            session_ref=ctx["session_ref"],
            actor_ref=ctx["actor_ref"],
            source=payload.source,
            campaign_id=payload.campaign_id,
            utm=payload.utm.model_dump(exclude_none=True) if payload.utm else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return result


@router.post("/call-link")
def call_link(session: DbSession, ctx: ClientContext, payload: WhatsAppLinkRequest) -> dict[str, Any]:
    try:
        result = leads_service.build_call_link(
            session,
            company_slug=payload.company_slug,
            branch_id=payload.branch_id,
            session_ref=ctx["session_ref"],
            actor_ref=ctx["actor_ref"],
            source=payload.source,
            campaign_id=payload.campaign_id,
            utm=payload.utm.model_dump(exclude_none=True) if payload.utm else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return result


@router.post("/leads", status_code=201)
def submit_lead(session: DbSession, ctx: ClientContext, payload: LeadSubmit) -> dict[str, Any]:
    try:
        lead, created = leads_service.submit_lead(
            session,
            payload.model_dump(exclude_none=True),
            session_ref=ctx["session_ref"],
            actor_ref=ctx["actor_ref"],
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session.commit()
    body = leads_service.serialize_lead(session, lead, include_contact=False)
    body["created"] = created
    body["next_steps_es"] = (
        "El comercio revisa la solicitud y confirma o rechaza. "
        "PRTDS no cobra comisión por este envío: solo un resultado confirmado "
        "con contrato genera ingreso."
    )
    return body


@router.get("/leads/{ref}")
def lead_status(session: DbSession, ref: str) -> dict[str, Any]:
    """Public read-back for the person who left the request.

    Contact data is never returned here (§13.4).
    """
    lead = leads_service.lead_by_ref(session, ref)
    if lead is None:
        raise HTTPException(status_code=404, detail="Solicitud inexistente.")
    payload = leads_service.serialize_lead(session, lead, include_contact=False)
    payload.pop("params", None)
    return payload


@router.get("/today")
def today_in_paraguay(session: DbSession) -> dict[str, Any]:
    """Daily utility block (§05): why open PRTDS without a purchase intent.

    Exchange rates and weather require a verified provider (§12) — the fields are
    returned explicitly as ``pending_provider`` instead of fabricated numbers.
    """
    week_since = utcnow() - timedelta(days=7)
    fresh = catalog.search(session, sort="recent", limit=5)
    return {
        "date_utc": utcnow().isoformat(),
        "recently_published": [
            {"slug": item["slug"], "display_name": item["display_name"], "category": item["category"]}
            for item in fresh["results"]
        ],
        "exchange_rate_bcp": {
            "status": "pending_provider",
            "note_es": "Requiere proveedor verificado (BCP). No se muestran valores estimados.",
            "reference": "https://www.bcp.gov.py",
        },
        "weather": {
            "status": "pending_provider",
            "note_es": "Requiere proveedor verificado. No se muestran valores estimados.",
        },
        "agenda_window_days": 7,
        "agenda_note_es": "Eventos verificados en el módulo Agenda (fuera de este corte).",
        "since": week_since.isoformat(),
        "generated_at": datetime.now().isoformat(),
    }
