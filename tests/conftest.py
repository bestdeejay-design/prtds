"""Test harness.

Each test starts from a freshly seeded demo dataset, so commercial facts created
by one test can never leak into another. The database is a temporary SQLite file
(production is PostgreSQL; the schema is dialect-portable).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP_DIR = Path(tempfile.mkdtemp(prefix="prtds-tests-"))
os.environ["PRTDS_DATABASE_URL"] = f"sqlite:///{_TMP_DIR / 'test.db'}"
os.environ["PRTDS_APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.seed.loader import reseed_all  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Token": settings.demo_admin_token}
OPS_HEADERS = {"X-Partner-Token": settings.demo_partner_token}

PARTNER_TOKENS = {
    "nails-mburucuya": "prtds-socio-nails",
    "rentcar-terere": "prtds-socio-rentcar",
    "supermercado-kaaguy": "prtds-socio-kaaguy",
    "almacen-dona-nidia": "prtds-socio-almacen",
    "tecnomovil-guarani": "prtds-socio-tecnomovil",
}


def partner_headers(company_slug: str) -> dict[str, str]:
    token = PARTNER_TOKENS.get(company_slug)
    if token is None:
        return dict(OPS_HEADERS)
    return {"X-Partner-Token": token}


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def fresh_dataset(client: TestClient) -> None:
    with SessionLocal() as session:
        reseed_all(session)
        session.commit()
    yield


def submit_lead(
    client: TestClient,
    company_slug: str,
    *,
    phone: str = "+595981111222",
    name: str = "Cliente de prueba",
    message: str = "Consulta de prueba",
    intent: str = "request",
    consent: bool = True,
    branch_id: str | None = None,
    offer_id: str | None = None,
) -> dict:
    payload = {
        "company_slug": company_slug,
        "branch_id": branch_id,
        "offer_id": offer_id,
        "intent": intent,
        "customer_name": name,
        "customer_phone": phone,
        "message": message,
        "requested_at": "viernes 18:00",
        "consent": {"purpose": "lead_transfer", "granted": consent, "channel": "test"},
    }
    return client.post("/api/leads", json=payload).json()


def accept_lead(client: TestClient, ref: str, company_slug: str, note: str = "ok") -> dict:
    response = client.post(
        f"/api/partner/leads/{ref}/decision",
        headers=partner_headers(company_slug),
        json={"status": "accepted", "note": note},
    )
    assert response.status_code == 200, response.text
    return response.json()


def confirm_sale(
    client: TestClient,
    ref: str,
    amount_pyg: int,
    company_slug: str,
    *,
    proof_ref: str = "FACT-TEST-1",
    is_repeat: bool = False,
) -> dict:
    response = client.post(
        f"/api/partner/leads/{ref}/sale",
        headers=partner_headers(company_slug),
        json={"amount_pyg": amount_pyg, "proof_ref": proof_ref, "is_repeat": is_repeat},
    )
    assert response.status_code == 200, response.text
    return response.json()
