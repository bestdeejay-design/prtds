"""Catalogue behaviour: publication pipeline, search quality, taxonomy and the
deterministic price engine.

Each assertion maps to a rule in the concept document (see the docstring refs).
"""

from __future__ import annotations

from tests.conftest import ADMIN_HEADERS


# --------------------------------------------------------------------------- #
# Publication pipeline (§13.2) — a registry row is not a public card
# --------------------------------------------------------------------------- #
def test_search_returns_only_published_companies(client):
    payload = client.get("/api/search", params={"limit": 50}).json()
    slugs = {item["slug"] for item in payload["results"]}
    assert "bodega-mboriahu-staging" not in slugs
    assert "taller-registro-maestro" not in slugs
    assert "nails-mburucuya" in slugs


def test_staging_card_is_not_reachable(client):
    response = client.get("/api/companies/bodega-mboriahu-staging")
    assert response.status_code == 404
    assert "registro maestro" in response.json()["detail"]


def test_registry_rows_are_not_counted_as_published_cards(client):
    stats = client.get("/api/admin/stats", headers=ADMIN_HEADERS).json()
    catalog = stats["catalog"]
    assert catalog["legal_entities_in_registry"] > catalog["published_cards"]
    assert catalog["company_records_total"] > catalog["published_cards"]
    assert catalog["by_status"].get("staging", 0) >= 1


def test_publication_pipeline_enforces_the_order(client):
    slug = "bodega-mboriahu-staging"

    illegal = client.post(
        f"/api/admin/companies/{slug}/publication",
        headers=ADMIN_HEADERS,
        json={"status": "published"},
    )
    assert illegal.status_code == 422
    assert "Transición no permitida" in illegal.json()["detail"]

    for status in ("validated", "moderated", "published"):
        response = client.post(
            f"/api/admin/companies/{slug}/publication",
            headers=ADMIN_HEADERS,
            json={"status": status},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == status

    assert client.get(f"/api/companies/{slug}").status_code == 200
    found = client.get("/api/search", params={"q": "bodega"}).json()
    assert any(item["slug"] == slug for item in found["results"])


# --------------------------------------------------------------------------- #
# Search quality for es-PY (§05, §02)
# --------------------------------------------------------------------------- #
def test_search_is_accent_insensitive(client):
    for query in ("movil", "móvil", "tecnomovil"):
        payload = client.get("/api/search", params={"q": query}).json()
        # the promoted card is served in the labelled advertising block only
        found = {item["slug"] for item in payload["results"]} | {
            item["slug"] for item in payload["sponsored"]["items"]
        }
        assert "tecnomovil-guarani" in found, query


def test_search_matches_every_token_of_a_multiword_query(client):
    payload = client.get("/api/search", params={"q": "alquiler auto"}).json()
    assert payload["total"] >= 1
    assert any(item["slug"] == "rentcar-terere" for item in payload["results"])


def test_search_uses_category_synonyms_as_data(client):
    payload = client.get("/api/search", params={"q": "medicamentos"}).json()
    assert any(item["slug"] == "farmacia-ysapy" for item in payload["results"])


def test_search_finds_products_not_only_companies(client):
    payload = client.get("/api/search", params={"q": "yerba mate"}).json()
    assert any(item["slug"] == "supermercado-kaaguy" for item in payload["results"])


def test_category_filter_includes_child_categories(client):
    payload = client.get("/api/search", params={"category": "belleza", "limit": 50}).json()
    slugs = {item["slug"] for item in payload["results"]}
    assert {"nails-mburucuya", "peluqueria-pora", "barberia-ypacarai"} <= slugs


def test_filters_by_barrio_channel_and_price(client):
    by_barrio = client.get("/api/search", params={"barrio": "Villa Morra"}).json()
    assert by_barrio["total"] >= 1
    assert all("Villa Morra" in item["barrios"] for item in by_barrio["results"])

    by_channel = client.get("/api/search", params={"channel": "whatsapp"}).json()
    assert all(item["primary_branch"]["channels"]["whatsapp"] for item in by_channel["results"])

    by_price = client.get(
        "/api/search", params={"category": "supermercados-cadena", "max_price": 20000}
    ).json()
    assert by_price["total"] >= 1


# --------------------------------------------------------------------------- #
# Advertising is labelled and separated (§13.4)
# --------------------------------------------------------------------------- #
def test_sponsored_results_are_separate_and_labelled(client):
    payload = client.get("/api/search", params={"q": "celular"}).json()
    sponsored = payload["sponsored"]
    assert sponsored["label_es"] == "Publicidad"
    assert any(item["slug"] == "tecnomovil-guarani" for item in sponsored["items"])
    # a promoted card must never silently mix into the organic ranking
    assert all(not item["is_promoted"] for item in payload["results"])
    assert "mejor oferta objetiva" in sponsored["note_es"]


# --------------------------------------------------------------------------- #
# Taxonomy is data, not code
# --------------------------------------------------------------------------- #
def test_categories_tree_is_nested_and_counted(client):
    payload = client.get("/api/categories").json()
    roots = {item["slug"]: item for item in payload["categories"]}
    assert "gastronomia" in roots
    child_slugs = {child["slug"] for child in roots["gastronomia"]["children"]}
    assert "restaurantes" in child_slugs
    assert roots["gastronomia"]["published_companies"] >= 1


def test_admin_can_create_a_category_with_synonyms_without_a_deploy(client):
    response = client.post(
        "/api/admin/categories",
        headers=ADMIN_HEADERS,
        json={
            "slug": "viveros",
            "name_es": "Viveros y jardinería",
            "parent_slug": "hogar",
            "default_intent": "whatsapp",
            "synonyms_es": ["plantas", "jardin"],
        },
    )
    assert response.status_code == 201, response.text

    tree = client.get("/api/categories").json()["categories"]
    hogar = next(item for item in tree if item["slug"] == "hogar")
    assert any(child["slug"] == "viveros" for child in hogar["children"])

    duplicate = client.post(
        "/api/admin/categories", headers=ADMIN_HEADERS, json={"slug": "viveros", "name_es": "Otra"}
    )
    assert duplicate.status_code == 422


def test_category_can_be_deactivated(client):
    response = client.patch(
        "/api/admin/categories/spa", headers=ADMIN_HEADERS, json={"is_active": False}
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    visible = {item["slug"] for item in client.get("/api/categories").json()["categories"]}
    assert "spa" not in visible


# --------------------------------------------------------------------------- #
# Deterministic price engine (§09, §08.2)
# --------------------------------------------------------------------------- #
def test_effective_price_separates_conditional_cashback(client):
    card = client.get("/api/companies/tecnomovil-guarani").json()
    offer = next(item for item in card["offers"] if item["sku"] == "TG-SM-128")
    price = offer["price"]

    assert price["base_price"] == 1_650_000
    assert price["seller_discount"] == 50_000
    # 10% = 165 000, capped by the rule at 150 000
    assert price["confirmed_benefits"] == 150_000
    assert price["effective_total"] == 1_450_000
    # 15% of the net amount, capped at 200 000, shown apart and labelled
    assert price["potential_cashback"] == 200_000
    assert price["potential_cashback_conditional"] is True
    assert price["potential_cashback"] not in (0, price["effective_total"])
    assert price["effective_total"] + price["potential_cashback"] != price["effective_total"]
    assert any("condicional" in item for item in price["rule_provenance"])


def test_card_exposes_freshness_and_source_for_every_offer(client):
    card = client.get("/api/companies/supermercado-kaaguy").json()
    assert card["offers"], "la ficha debe publicar ofertas"
    for offer in card["offers"]:
        assert offer["freshness"]["source"]
        assert offer["freshness"]["observed_at"]
        assert offer["freshness"]["verification_level"]
        assert offer["currency"] == "PYG"
        # PYG is displayed without fractional units
        assert "," not in offer["price_display"]


def test_card_lists_clear_actions_for_a_narrow_screen(client):
    card = client.get("/api/companies/nails-mburucuya").json()
    branch = card["branches"][0]
    assert branch["channels"]["whatsapp"]
    assert branch["map_url"].startswith("https://www.openstreetmap.org/")
    assert set(card["actions_es"]) >= {"whatsapp", "call", "route", "request"}


def test_search_reindex_endpoint_is_idempotent(client):
    first = client.get("/api/search", params={"q": "yerba"}).json()["total"]
    response = client.post("/api/admin/reindex", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    assert response.json()["reindexed_companies"] >= 1
    second = client.get("/api/search", params={"q": "yerba"}).json()["total"]
    assert first == second
