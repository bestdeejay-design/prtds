"""FastAPI application factory.

One process serves both the API and the mobile-first frontend (vanilla ES
modules, no build step). That keeps the browser-facing code free of absolute
hosts: everything is relative, so the same bundle runs behind the sandbox
preview proxy, behind a Cloudflare Worker or behind Render.

Startup order (dev):
    1. create the schema if the database is empty (production uses Alembic);
    2. seed the demo dataset if the catalogue is empty;
    3. mount static assets and page routes.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api import admin as admin_api
from app.api import partner as partner_api
from app.api import public as public_api
from app.core.config import settings
from app.core.db import Base, SessionLocal, engine, get_session
from app.domain.models import Company
from app.modules import catalog, commerce

logger = logging.getLogger("prtds")

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"


def init_dev_database() -> dict[str, object]:
    """Create tables and seed demo data when the database is empty.

    Production must run ``alembic upgrade head`` instead; this helper only
    bootstraps a local environment so the team does not depend on one machine.
    """
    from app.domain import models  # noqa: F401  (registers mappers)

    Base.metadata.create_all(engine)

    with SessionLocal() as session:
        existing = session.scalar(select(Company.id).limit(1))
        if existing is None:
            from app.seed.loader import seed_all

            report = seed_all(session)
            session.commit()
            logger.info("seeded demo dataset: %s companies", report.get("companies"))
            return {"seeded": True, **report}
    return {"seeded": False}


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.bootstrap = init_dev_database()
    except SQLAlchemyError:  # pragma: no cover - defensive
        logger.exception("database bootstrap failed; the API starts empty")
        app.state.bootstrap = {"seeded": False, "error": "bootstrap_failed"}
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="PRTDS — plataforma digital de Paraguay",
        version="0.1.0",
        summary=(
            "Corte 1: recorrido completo búsqueda → ficha → WhatsApp/solicitud → "
            "estado CRM → resultado confirmado → base de comisión."
        ),
        description=(
            "Documento interno. No es una promesa de ingresos ni una confirmación "
            "de que todos los servicios descritos estén en producción."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(public_api.router)
    app.include_router(partner_api.router)
    app.include_router(admin_api.router)

    # ---- error contract ---------------------------------------------------
    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Datos inválidos.",
                "errors": [
                    {
                        "field": ".".join(str(part) for part in err.get("loc", [])),
                        "message": err.get("msg"),
                    }
                    for err in exc.errors()
                ],
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("database error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Error de base de datos. Nada fue confirmado."},
        )

    # ---- honest state panel ----------------------------------------------
    @app.get("/api/meta/status", tags=["meta"])
    def platform_status(session: Session = Depends(get_session)) -> dict:
        """What exists, what is still to be verified (§12, §15)."""
        return {
            "slice": "corte-1: funnel de punta a punta",
            "app_env": settings.app_env,
            "catalog": catalog.registry_vs_public(session),
            "economics": commerce.revenue_summary(session),
            "pending_verification_es": [
                "Auditoría read-only de producción (Neon, Render, Cloudflare).",
                "Proveedores verificados de tipo de cambio y clima.",
                "Identidad real de usuarios y socios (no tokens de demostración).",
                "Integración POS/feed con cadenas grandes.",
                "Análisis jurídico de bonos, cashback y productos financieros.",
            ],
            "demo_data_notice_es": (
                "Los datos del catálogo local son ficticios y sirven para validar "
                "el recorrido; no son ofertas reales ni socios contratados."
            ),
        }

    # ---- frontend pages ----------------------------------------------------
    if FRONTEND_DIR.exists():
        assets_dir = FRONTEND_DIR / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        def page_route(path: str, filename: str) -> None:
            file_path = FRONTEND_DIR / filename

            async def handler(request: Request) -> Response:
                if not file_path.exists():
                    return JSONResponse(status_code=500, content={"detail": f"falta {filename}"})
                return FileResponse(file_path)

            # response_model=None: a page route returns a file, not a Pydantic model
            app.add_api_route(
                path, handler, methods=["GET"], include_in_schema=False, response_model=None
            )

        page_route("/", "index.html")
        page_route("/busqueda", "index.html")
        page_route("/empresa/{slug}", "company.html")
        page_route("/solicitud", "lead.html")
        page_route("/solicitud/", "lead.html")
        page_route("/solicitud/{ref}", "lead.html")
        page_route("/socio", "partner.html")
        page_route("/admin", "admin.html")
        page_route("/salud", "status.html")

    return app


app = create_app()
