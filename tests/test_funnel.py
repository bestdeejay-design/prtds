"""Funnel discipline (§07, §13.4): what an event proves, consent, idempotency
and the separation between an attempt to contact and a delivered request.
"""

from __future__ import annotations

from tests.conftest import ADMIN_HEADERS, submit_lead

SESSION = {"X-PRTDS-Session": "test-session-funnel"}


def test_public_ingest_refuses_commercial_facts(client):
    response = client.post(
        "/api/events", headers=SESSION, json={"event_type": "sale_confirmed", "amount_pyg": 100000}
    )
    assert response.status_code == 422
    assert "hechos comerciales" in response.json()["detail"]


def test_unknown_event_type_is_rejected(client):
    response = client.post("/api/events", headers=SESSION, json={"event_type": "cliente_feliz"})
    assert response.status_code == 422


def test_event_response_states_what_it_does_not_prove(client):
    response = client.post(
        "/api/events",
        headers=SESSION,
        json={"event_type": "whatsapp_click", "company_slug": "nails-mburucuya", "source": "test"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["event_type"] == "whatsapp_click"
    assert "venta" in body["does_not_prove_es"].lower() or "conversación" in body["does_not_prove_es"]


def test_repeated_impressions_are_deduplicated(client):
    first = client.post(
        "/api/events",
        headers=SESSION,
        json={
            "event_type": "card_open",
            "company_slug": "nails-mburucuya",
            "source": "test",
            "idempotency_key": "test-fixed-key-1",
        },
    ).json()
    second = client.post(
        "/api/events",
        headers=SESSION,
        json={
            "event_type": "card_open",
            "company_slug": "nails-mburucuya",
            "source": "test",
            "idempotency_key": "test-fixed-key-1",
        },
    ).json()

    assert first["created"] is True
    assert second["created"] is False
    assert second["deduplicated"] is True
    assert first["event_id"] == second["event_id"]

    events = client.get(
        "/api/admin/funnel/events",
        headers=ADMIN_HEADERS,
        params={"event_type": "card_open", "company_slug": "nails-mburucuya"},
    ).json()
    assert sum(1 for event in events["events"] if event["id"] == first["event_id"]) == 1


def test_card_open_is_recorded_once_per_visit(client):
    headers = {"X-PRTDS-Session": "card-open-visit-1"}
    client.get("/api/companies/parrilla-yvoty", headers=headers)
    client.get("/api/companies/parrilla-yvoty", headers=headers)

    events = client.get(
        "/api/admin/funnel/events",
        headers=ADMIN_HEADERS,
        params={"event_type": "card_open", "company_slug": "parrilla-yvoty"},
    ).json()["events"]
    assert len(events) == 1


def test_whatsapp_link_is_an_attempt_with_a_reference(client):
    response = client.post(
        "/api/whatsapp-link",
        headers=SESSION,
        json={"company_slug": "nails-mburucuya", "source": "test"},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["url"].startswith("https://wa.me/595")
    assert "text=" in body["url"]
    assert body["reference"] in body["message"]
    assert "intento de contacto" in body["disclaimer_es"].lower()

    events = client.get(
        "/api/admin/funnel/events",
        headers=ADMIN_HEADERS,
        params={"event_type": "whatsapp_click", "company_slug": "nails-mburucuya"},
    ).json()["events"]
    assert len(events) == 1
    assert events[0]["amount_pyg"] is None  # an attempt carries no money


def test_whatsapp_link_refused_when_no_verified_channel(client):
    response = client.post(
        "/api/whatsapp-link", headers=SESSION, json={"company_slug": "estudio-contable-aty"}
    )
    assert response.status_code == 404
    assert "WhatsApp" in response.json()["detail"]


def test_lead_requires_explicit_consent(client):
    payload = submit_lead(client, "nails-mburucuya", consent=False)
    assert payload["detail"]
    response = client.post(
        "/api/leads",
        json={
            "company_slug": "nails-mburucuya",
            "consent": {"purpose": "lead_transfer", "granted": False},
        },
    )
    assert response.status_code == 403
    assert "consentimiento" in response.json()["detail"].lower()


def test_lead_stores_a_prefilled_message_with_the_reference(client):
    created = submit_lead(client, "nails-mburucuya", message="Quiero turno el viernes")
    ref = created["ref_code"]

    detail = client.get(f"/api/leads/{ref}").json()
    assert ref in detail["prefilled_message"]
    assert "Nails Mburucuyá" in detail["prefilled_message"]
    # public read-back never returns contact data
    assert "customer_phone" not in detail
    assert "customer_name" not in detail


def test_same_request_twice_is_one_lead(client):
    first = submit_lead(client, "nails-mburucuya", phone="+595981777888")
    second = submit_lead(client, "nails-mburucuya", phone="+595981777888")
    assert first["ref_code"] == second["ref_code"]
    assert first["created"] is True
    assert second["created"] is False


def test_lead_submission_emits_a_consent_bound_event(client):
    created = submit_lead(client, "rentcar-terere")
    events = client.get(
        "/api/admin/funnel/events",
        headers=ADMIN_HEADERS,
        params={"event_type": "lead_submitted", "company_slug": "rentcar-terere"},
    ).json()["events"]
    assert len(events) == 1
    assert events[0]["actor_kind"] in ("user", "anonymous")
    assert created["attribution"] is not None
    assert created["attribution"]["window_days"] == 7


def test_attribution_prefers_the_last_meaningful_touch(client):
    session_headers = {"X-PRTDS-Session": "attribution-visit"}
    client.get("/api/companies/rentcar-terere", headers=session_headers)
    client.post(
        "/api/whatsapp-link",
        headers=session_headers,
        json={"company_slug": "rentcar-terere", "source": "instagram", "campaign_id": "camp-01"},
    )
    created = submit_lead(client, "rentcar-terere", phone="+595981000111")

    attribution = created["attribution"]
    assert attribution["channel"] == "instagram"
    assert attribution["campaign_id"] == "camp-01"
    assert attribution["method"] == "utm"
    assert attribution["confidence"] in ("high", "medium")


def test_funnel_dictionary_is_exposed_to_clients(client):
    payload = client.get("/api/meta/funnel").json()
    codes = {event["code"] for event in payload["events"]}
    assert {"search_result", "card_open", "whatsapp_click", "lead_submitted", "sale_confirmed"} <= codes
    assert payload["not_equivalent_es"]
    sale = next(event for event in payload["events"] if event["code"] == "sale_confirmed")
    assert sale["commissionable"] is True
    click = next(event for event in payload["events"] if event["code"] == "whatsapp_click")
    assert click["commissionable"] is False


def test_market_metadata_declares_pyg_without_decimals(client):
    payload = client.get("/api/meta/market").json()
    assert payload["currency"] == "PYG"
    assert payload["currency_decimals"] == 0
    assert payload["locale"] == "es-PY"
    assert payload["timezone"] == "America/Asuncion"
    assert any(language["code"] == "gn" for language in payload["languages"])
