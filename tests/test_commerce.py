"""The commercial rules that must never be bent (§06, §10, §13.4, §15).

These tests are the executable form of the concept document's hard rules:
  * a click never creates a commission;
  * revenue appears only with contract + confirmed event + fulfilled service;
  * one confirmed result produces exactly one commission;
  * GMV is not PRTDS revenue;
  * a non-positive contribution margin is flagged, not hidden.
"""

from __future__ import annotations

from tests.conftest import (
    ADMIN_HEADERS,
    OPS_HEADERS,
    accept_lead,
    confirm_sale,
    partner_headers,
    submit_lead,
)


def test_full_path_from_lead_to_commission(client):
    lead = submit_lead(client, "nails-mburucuya", intent="booking")
    ref = lead["ref_code"]

    accept_lead(client, ref, "nails-mburucuya")

    result = confirm_sale(client, ref, 180_000, "nails-mburucuya", proof_ref="FACT-0001")
    settlement = result["settlement"]

    # 7% of 180 000 G. = 12 600 G. of PRTDS revenue, minus 4 000 G. variable costs
    assert settlement["basis_amount_pyg"] == 180_000
    assert settlement["commission_amount_pyg"] == 12_600
    assert settlement["contribution_margin_pyg"] == 8_600
    assert settlement["status"] == "pending"
    assert settlement["rule"]["rate_percent"] == 7.0
    assert result["lead"]["status"] == "sale_confirmed"
    assert result["event"]["event_type"] == "sale_confirmed"


def test_gmv_is_not_prtds_revenue(client):
    lead = submit_lead(client, "nails-mburucuya")
    confirm_sale(client, lead["ref_code"], 180_000, "nails-mburucuya")

    economics = client.get("/api/partner/dashboard", headers=partner_headers("nails-mburucuya")).json()[
        "economics"
    ]
    assert economics["gmv_pyg"] == 180_000
    assert economics["prtds_revenue_pyg"] == 12_600
    assert economics["prtds_revenue_pyg"] != economics["gmv_pyg"]
    assert economics["warning_es"]


def test_confirmed_sale_without_contract_yields_zero_commission(client):
    """§06: a free directory listing never produces a commission "per click"."""
    lead = submit_lead(client, "parrilla-yvoty")
    ref = lead["ref_code"]

    result = confirm_sale(client, ref, 185_000, "parrilla-yvoty", proof_ref="TICKET-77")
    settlement = result["settlement"]

    assert settlement["status"] == "no_contract_basis"
    assert settlement["commission_amount_pyg"] == 0
    assert settlement["basis_amount_pyg"] == 185_000  # the sale still counts as GMV
    assert "contrato" in settlement["status_reason_es"].lower()

    economics = client.get("/api/partner/dashboard", headers=OPS_HEADERS).json()["economics"]
    assert economics["prtds_revenue_pyg"] == 0
    assert any(alert["code"] == "no_contract_basis" and alert["count"] >= 1 for alert in economics["alerts"])


def test_replaying_a_confirmation_never_creates_a_second_commission(client):
    lead = submit_lead(client, "nails-mburucuya")
    ref = lead["ref_code"]
    accept_lead(client, ref, "nails-mburucuya")

    first = confirm_sale(client, ref, 180_000, "nails-mburucuya", proof_ref="FACT-0002")
    replay = confirm_sale(client, ref, 180_000, "nails-mburucuya", proof_ref="FACT-0002")

    assert replay["settlement"]["id"] == first["settlement"]["id"]
    assert replay["event"]["id"] == first["event"]["id"]

    settlements = client.get("/api/partner/settlements", headers=partner_headers("nails-mburucuya")).json()
    assert settlements["total"] == 1
    assert settlements["settlements"][0]["commission_amount_pyg"] == 12_600


def test_two_different_receipts_are_two_operations(client):
    lead = submit_lead(client, "nails-mburucuya")
    ref = lead["ref_code"]
    accept_lead(client, ref, "nails-mburucuya")

    confirm_sale(client, ref, 70_000, "nails-mburucuya", proof_ref="FACT-A")
    second = confirm_sale(client, ref, 95_000, "nails-mburucuya", proof_ref="FACT-B", is_repeat=True)

    assert second["event"]["event_type"] == "repeat_purchase"
    settlements = client.get("/api/partner/settlements", headers=partner_headers("nails-mburucuya")).json()
    assert settlements["total"] == 2
    assert sum(row["commission_amount_pyg"] for row in settlements["settlements"]) == round(70_000 * 0.07) + round(
        95_000 * 0.07
    )


def test_negative_contribution_margin_is_flagged_not_hidden(client):
    """§10 hard rule: commission − PRTDS-funded discounts − variable costs > 0."""
    lead = submit_lead(client, "almacen-dona-nidia")
    ref = lead["ref_code"]
    accept_lead(client, ref, "almacen-dona-nidia")

    settlement = confirm_sale(client, ref, 100_000, "almacen-dona-nidia")["settlement"]

    # 1% of 100 000 = 1 000 G. commission against 50 000 G. of variable costs
    assert settlement["commission_amount_pyg"] == 1_000
    assert settlement["contribution_margin_pyg"] == -49_000
    assert settlement["status"] == "flagged_negative_cm"
    assert "margen" in settlement["status_reason_es"].lower()

    economics = client.get("/api/partner/dashboard", headers=partner_headers("almacen-dona-nidia")).json()[
        "economics"
    ]
    assert economics["settlements_by_status"]["flagged_negative_cm"] == 1
    # the loss stays visible in its own field instead of vanishing from revenue
    assert economics["flagged_negative_margin_pyg"] == -49_000
    assert economics["prtds_revenue_pyg"] == 0
    assert economics["contribution_margin_pyg"] == 0


def test_per_event_cap_limits_the_commission(client):
    lead = submit_lead(client, "supermercado-kaaguy")
    ref = lead["ref_code"]
    accept_lead(client, ref, "supermercado-kaaguy")

    settlement = confirm_sale(client, ref, 10_000_000, "supermercado-kaaguy")["settlement"]

    # 3% of 10 000 000 = 300 000, capped by rule at 120 000 per event
    assert settlement["rate_bps"] == 300
    assert settlement["commission_amount_pyg"] == 120_000
    assert settlement["cap_applied"] is True


def test_contract_period_cap_limits_total_commission(client):
    lead_a = submit_lead(client, "nails-mburucuya", phone="+595981100001")
    accept_lead(client, lead_a["ref_code"], "nails-mburucuya")
    confirm_sale(client, lead_a["ref_code"], 20_000_000, "nails-mburucuya", proof_ref="FACT-CAP-1")

    # 7% of 20 000 000 = 1 400 000, still below the 2 000 000 monthly cap
    first = client.get("/api/partner/settlements", headers=partner_headers("nails-mburucuya")).json()
    assert first["settlements"][0]["commission_amount_pyg"] == 1_400_000

    lead_b = submit_lead(client, "nails-mburucuya", phone="+595981100002")
    accept_lead(client, lead_b["ref_code"], "nails-mburucuya")
    confirm_sale(client, lead_b["ref_code"], 20_000_000, "nails-mburucuya", proof_ref="FACT-CAP-2")

    settlements = client.get("/api/partner/settlements", headers=partner_headers("nails-mburucuya")).json()[
        "settlements"
    ]
    capped = next(row for row in settlements if row["commission_amount_pyg"] != 1_400_000)
    assert capped["commission_amount_pyg"] == 600_000  # 2 000 000 − 1 400 000
    assert capped["cap_applied"] is True


def test_minimum_amount_rule_produces_no_commission(client):
    lead = submit_lead(client, "rentcar-terere")
    ref = lead["ref_code"]
    accept_lead(client, ref, "rentcar-terere")

    settlement = confirm_sale(client, ref, 100_000, "rentcar-terere")["settlement"]
    assert settlement["commission_amount_pyg"] == 0
    assert "mínimo" in settlement["status_reason_es"]


def test_partner_cannot_touch_another_company_lead(client):
    lead = submit_lead(client, "rentcar-terere")
    response = client.post(
        f"/api/partner/leads/{lead['ref_code']}/decision",
        headers=partner_headers("nails-mburucuya"),
        json={"status": "accepted"},
    )
    assert response.status_code == 403


def test_invalid_crm_transition_is_refused(client):
    lead = submit_lead(client, "nails-mburucuya")
    ref = lead["ref_code"]

    response = client.post(
        f"/api/partner/leads/{ref}/decision",
        headers=partner_headers("nails-mburucuya"),
        json={"status": "visit_done"},
    )
    assert response.status_code == 422
    assert "transición no permitida" in response.json()["detail"].lower()

    # a rejected request can be reversed by manual reconciliation, with a note
    reject = client.post(
        f"/api/partner/leads/{ref}/decision",
        headers=partner_headers("nails-mburucuya"),
        json={"status": "rejected", "rejection_reason_es": "Sin disponibilidad"},
    )
    assert reject.status_code == 200
    reverse = client.post(
        f"/api/partner/leads/{ref}/decision",
        headers=partner_headers("nails-mburucuya"),
        json={"status": "accepted", "note": "Cliente llamó y hay turno"},
    )
    assert reverse.status_code == 200


def test_sale_cannot_be_confirmed_through_the_public_event_api(client):
    response = client.post(
        "/api/events", json={"event_type": "sale_confirmed", "amount_pyg": 500_000}
    )
    assert response.status_code == 422


def test_funnel_counters_match_the_ledger(client):
    lead = submit_lead(client, "nails-mburucuya")
    accept_lead(client, lead["ref_code"], "nails-mburucuya")
    confirm_sale(client, lead["ref_code"], 180_000, "nails-mburucuya")

    dashboard = client.get("/api/partner/dashboard", headers=partner_headers("nails-mburucuya")).json()
    counts = {event["code"]: event["count"] for event in dashboard["funnel"]["events"]}

    assert counts["lead_submitted"] == 1
    assert counts["lead_accepted"] == 1
    assert counts["sale_confirmed"] == 1
    assert counts["settlement_created"] == 1
    assert dashboard["funnel"]["leads_by_status"]["sale_confirmed"] == 1
    assert dashboard["funnel"]["conversion"]["lead_acceptance_rate"] == 1.0


def test_admin_can_dispute_a_settlement(client):
    lead = submit_lead(client, "nails-mburucuya")
    accept_lead(client, lead["ref_code"], "nails-mburucuya")
    settlement = confirm_sale(client, lead["ref_code"], 180_000, "nails-mburucuya")["settlement"]

    response = client.post(
        f"/api/admin/settlements/{settlement['id']}/dispute",
        headers=ADMIN_HEADERS,
        params={"reason": "El comercio niega la operación"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "disputed"

    economics = client.get("/api/admin/stats", headers=ADMIN_HEADERS).json()["economics"]
    assert economics["prtds_revenue_pyg"] == 0  # a disputed settlement is not revenue
