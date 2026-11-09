"""Builds the demo dataset inside a session.

Idempotent: if the catalogue already has companies the loader refuses to seed
again unless ``force=True`` (which clears the demo tables first). Production
never calls this module — real data arrives through the
staging → validation → moderation → publication pipeline (§13.2).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.ids import new_id, utcnow
from app.core.money import pct_to_bps
from app.core.security import hash_token
from app.domain.models import (
    BenefitRule,
    BillingModel,
    Brand,
    Branch,
    CapPeriod,
    Category,
    ChannelType,
    CommissionRule,
    Company,
    CompanyCategory,
    Consent,
    Contact,
    Contract,
    ContractStatus,
    FunnelEvent,
    Lead,
    LeadAttribution,
    LegalEntity,
    Offer,
    PartnerRole,
    PartnerUser,
    PublicationStatus,
    Settlement,
    Source,
    VerificationLevel,
)
from app.modules import catalog as catalog_service
from app.modules import commerce
from app.seed import data

OBSERVED_OFFSET_HOURS = 6


def _published_status(raw: str | None) -> PublicationStatus:
    return PublicationStatus(raw or "published")


def _verification(raw: str | None) -> VerificationLevel:
    return VerificationLevel(raw or "source_only")


def clear_demo(session: Session) -> dict[str, int]:
    """Delete demo rows (dev only). Never run against production data."""
    counts: dict[str, int] = {}
    # Deletion order respects foreign keys (SQLite runs with PRAGMA foreign_keys=ON).
    for model in (
        Settlement,
        LeadAttribution,
        FunnelEvent,
        Lead,
        Consent,
        PartnerUser,
        Contract,
        CommissionRule,
        BenefitRule,
        Offer,
        Contact,
        CompanyCategory,
        Branch,
        Company,
        Brand,
        LegalEntity,
        Category,
        Source,
    ):
        rows = session.scalars(select(model)).all()
        counts[model.__tablename__] = len(rows)
        for row in rows:
            session.delete(row)
    session.flush()
    return counts


def seed_all(session: Session, *, force: bool = False) -> dict[str, Any]:
    existing = session.scalar(select(func.count(Company.id))) or 0
    if existing and not force:
        return {"companies": int(existing), "skipped": True}
    if existing and force:
        clear_demo(session)

    now = utcnow()
    observed = now - timedelta(hours=OBSERVED_OFFSET_HOURS)

    # ---- sources ----------------------------------------------------------
    sources: dict[str, Source] = {}
    for spec in data.SOURCES:
        source = Source(
            id=new_id("source"),
            name=spec["name"],
            kind=spec["kind"],
            url=spec.get("url"),
            retrieved_at=observed,
            license_note=spec.get("license_note"),
            trusted=spec.get("trusted", False),
        )
        session.add(source)
        sources[spec["key"]] = source
    session.flush()

    # ---- categories (tree) -------------------------------------------------
    categories: dict[str, Category] = {}

    def add_category(spec: dict[str, Any], parent_id: str | None) -> Category:
        category = Category(
            id=new_id("category"),
            slug=spec["slug"],
            name_es=spec["name_es"],
            name_ru=spec.get("name_ru"),
            description_es=spec.get("description_es"),
            parent_id=parent_id,
            sort_order=spec.get("sort_order", 100),
            default_intent=spec.get("default_intent", "whatsapp"),
            icon=spec.get("icon"),
            synonyms_es=spec.get("synonyms_es"),
            is_active=spec.get("is_active", True),
        )
        session.add(category)
        categories[spec["slug"]] = category
        session.flush()
        for child in spec.get("children", []):
            add_category(child, category.id)
        return category

    for spec in data.CATEGORIES:
        add_category(spec, None)

    # ---- legal entities ----------------------------------------------------
    legal_entities: dict[str, LegalEntity] = {}

    def add_legal_entity(spec: dict[str, Any]) -> LegalEntity:
        entity = LegalEntity(
            id=new_id("legal_entity"),
            name=spec["name"],
            ruc=spec.get("ruc"),
            country="PY",
            legal_form="S.A." if "S.A." in spec["name"] else "E.I.R.L.",
            is_active=True,
            source_id=sources["manual"].id,
            observed_at=observed,
            verification_level=VerificationLevel.SOURCE_ONLY,
            updated_by="seed",
        )
        session.add(entity)
        session.flush()
        legal_entities[spec["ruc"] or spec["name"]] = entity
        return entity

    for spec in data.EXTRA_LEGAL_ENTITIES:
        add_legal_entity(spec)

    # ---- brands, companies, branches, offers --------------------------------
    brands: dict[str, Brand] = {}
    companies: dict[str, Company] = {}

    for spec in data.COMPANIES:
        legal = add_legal_entity(spec["legal"]) if spec.get("legal") else None

        brand = None
        if spec.get("brand"):
            slug = spec["brand"].lower().replace(" ", "-")
            brand = brands.get(slug)
            if brand is None:
                brand = Brand(
                    id=new_id("brand"),
                    name=spec["brand"],
                    slug=slug,
                    legal_entity_id=legal.id if legal else None,
                    source_id=sources["partner"].id,
                    observed_at=observed,
                    verification_level=_verification(spec.get("verification")),
                    updated_by="seed",
                )
                session.add(brand)
                session.flush()
                brands[slug] = brand

        status = _published_status(spec.get("status"))
        primary_category = categories.get(spec["category"])
        company = Company(
            id=new_id("company"),
            slug=spec["slug"],
            display_name=spec["display_name"],
            search_text=" ".join(
                filter(None, [spec.get("short", ""), spec.get("description", ""), spec.get("brand", "")])
            ),
            short_description_es=spec.get("short"),
            description_es=spec.get("description") or spec.get("short"),
            brand_id=brand.id if brand else None,
            legal_entity_id=legal.id if legal else None,
            primary_category_id=primary_category.id if primary_category else None,
            publication_status=status,
            published_at=now - timedelta(days=spec.get("published_days_ago", 3))
            if status is PublicationStatus.PUBLISHED
            else None,
            is_promoted=bool(spec.get("promoted")),
            promoted_until=now + timedelta(days=30) if spec.get("promoted") else None,
            verification_level=_verification(spec.get("verification")),
            source_id=sources["partner" if spec.get("verification") == "partner_confirmed" else "manual"].id,
            observed_at=observed,
            valid_until=observed + timedelta(days=60),
            updated_by="seed",
            quality={
                "contacts_verified": bool(spec.get("verification") in ("partner_confirmed", "field_verified")),
                "hours_declared": True,
                "duplicates": 0,
                "demo": True,
            },
        )
        session.add(company)
        session.flush()
        companies[spec["slug"]] = company

        if primary_category:
            session.add(CompanyCategory(company_id=company.id, category_id=primary_category.id))
        for extra in spec.get("extra_categories", []):
            extra_category = categories.get(extra)
            if extra_category:
                session.add(CompanyCategory(company_id=company.id, category_id=extra_category.id))

        for branch_spec in spec.get("branches", []):
            branch = Branch(
                id=new_id("branch"),
                company_id=company.id,
                name_es=branch_spec["name_es"],
                address_text=branch_spec.get("address_text"),
                barrio=branch_spec.get("barrio"),
                city=branch_spec.get("city", "Asunción"),
                district=branch_spec.get("city", "Asunción"),
                latitude=branch_spec.get("latitude"),
                longitude=branch_spec.get("longitude"),
                phone_e164=branch_spec.get("phone_e164"),
                whatsapp_e164=branch_spec.get("whatsapp_e164"),
                opening_hours=branch_spec.get("opening_hours"),
                pickup_available=branch_spec.get("pickup_available", True),
                delivery_available=branch_spec.get("delivery_available", False),
                delivery_fee_pyg=branch_spec.get("delivery_fee_pyg", 0),
                delivery_zone_es=branch_spec.get("delivery_zone_es"),
                publication_status=_published_status(branch_spec.get("publication_status")),
                source_id=sources["osm"].id,
                observed_at=observed,
                verification_level=_verification(spec.get("verification")),
                valid_from=observed,
                valid_until=observed + timedelta(days=90),
                updated_by="seed",
            )
            session.add(branch)
            session.flush()

            # Contact is a first-class shared entity: every declared channel of
            # the branch is registered with its own verification metadata.
            channel_specs = [
                ("whatsapp", branch.whatsapp_e164, True, "WhatsApp del local"),
                ("phone", branch.phone_e164, not branch.whatsapp_e164, "Teléfono fijo"),
                ("email", branch.email, True, "Correo"),
                ("website", branch.website_url, True, "Sitio web"),
                ("instagram", branch.instagram_handle, True, "Instagram"),
            ]
            for channel, value, is_primary, label in channel_specs:
                if not value:
                    continue
                session.add(
                    Contact(
                        id=new_id("contact"),
                        branch_id=branch.id,
                        channel=ChannelType(channel),
                        value=value,
                        label_es=label,
                        is_primary=bool(is_primary),
                        verified_at=observed
                        if spec.get("verification") in ("partner_confirmed", "field_verified")
                        else None,
                        source_id=sources["partner" if spec.get("verification") == "partner_confirmed" else "manual"].id,
                        observed_at=observed,
                        verification_level=_verification(spec.get("verification")),
                        valid_until=observed + timedelta(days=90),
                        updated_by="seed",
                    )
                )
            session.flush()

        for index, offer_spec in enumerate(spec.get("offers", []), start=1):
            offer_category = categories.get(spec["category"])
            branch_row = session.scalar(
                select(Branch).where(Branch.company_id == company.id).limit(1)
            )
            offer = Offer(
                id=new_id("offer"),
                company_id=company.id,
                branch_id=branch_row.id if branch_row else None,
                category_id=offer_category.id if offer_category else None,
                sku=offer_spec.get("sku") or f"{spec['slug'][:6].upper()}-{index:03d}",
                barcode=(offer_spec.get("attributes") or {}).get("barcode"),
                title_es=offer_spec["title_es"],
                description_es=offer_spec.get("description_es"),
                currency="PYG",
                base_price=int(offer_spec["base_price"]),
                seller_discount=int(offer_spec.get("seller_discount", 0)),
                unit=offer_spec.get("unit"),
                availability_status=offer_spec.get("availability_status", "in_stock"),
                is_active=True,
                attributes={**(offer_spec.get("attributes") or {}), "demo": True},
                source_id=sources["partner"].id,
                observed_at=observed,
                verification_level=_verification(spec.get("verification")),
                valid_from=observed,
                valid_until=observed + timedelta(days=30),
                updated_by="seed",
            )
            session.add(offer)
        session.flush()

    # ---- search index (accent-folded blob for es-PY queries) ----------------
    for company in companies.values():
        catalog_service.refresh_search_text(session, company)

    # ---- commission rules ---------------------------------------------------
    rules: dict[str, CommissionRule] = {}
    for spec in data.COMMISSION_RULES:
        rule = CommissionRule(
            id=new_id("rule"),
            name=spec["name"],
            scope=spec["scope"],
            company_id=companies[spec["company_slug"]].id if spec.get("company_slug") else None,
            category_id=categories[spec["category_slug"]].id if spec.get("category_slug") else None,
            applies_to=spec.get("applies_to", "sale_confirmed"),
            rate_bps=pct_to_bps(spec["rate_percent"]) if spec.get("rate_percent") else 0,
            fixed_amount_pyg=int(spec.get("fixed_amount_pyg", 0)),
            min_amount_pyg=int(spec.get("min_amount_pyg", 0)),
            max_amount_per_event_pyg=spec.get("max_amount_per_event_pyg"),
            priority=int(spec.get("priority", 100)),
            is_active=True,
            notes=spec.get("notes"),
        )
        session.add(rule)
        rules[spec["name"]] = rule
    session.flush()

    # ---- benefit rules (deterministic price engine input) --------------------
    for spec in data.BENEFIT_RULES:
        session.add(
            BenefitRule(
                id=new_id("rule"),
                code=spec["code"],
                source_kind=spec["source_kind"],
                financier=spec["financier"],
                presentation_type=spec.get("presentation_type", "promo_code"),
                company_id=companies[spec["company_slug"]].id if spec.get("company_slug") else None,
                category_id=categories[spec["category_slug"]].id if spec.get("category_slug") else None,
                kind=spec.get("kind", "percent"),
                value_bps=int(spec.get("value_bps", 0)),
                fixed_amount_pyg=int(spec.get("fixed_amount_pyg", 0)),
                cap_amount_pyg=spec.get("cap_amount_pyg"),
                is_conditional=bool(spec.get("is_conditional")),
                guaranteed=bool(spec.get("guaranteed", True)),
                conditions_es=spec.get("conditions_es"),
                is_active=True,
                source_id=sources["partner"].id,
                observed_at=observed,
                verification_level=VerificationLevel.PARTNER_CONFIRMED,
                valid_from=observed - timedelta(days=1),
                valid_until=observed + timedelta(days=45),
                updated_by="seed",
            )
        )
    session.flush()

    # ---- contracts + partner users ------------------------------------------
    partner_users: list[PartnerUser] = []
    for spec in data.CONTRACTS:
        company = companies.get(spec["company_slug"])
        if company is None:
            continue
        contract = Contract(
            id=new_id("contract"),
            company_id=company.id,
            number=spec["number"],
            counterparty_name=spec["counterparty_name"],
            contact_name=spec.get("contact_name"),
            status=ContractStatus.ACTIVE,
            billing_model=BillingModel(spec["billing_model"]),
            commission_rule_id=rules[spec["rule_name"]].id if spec.get("rule_name") in rules else None,
            signed_at=now - timedelta(days=10),
            valid_from=now - timedelta(days=10),
            valid_to=now + timedelta(days=355),
            attribution_window_days=int(spec.get("attribution_window_days", 7)),
            cap_amount_pyg=spec.get("cap_amount_pyg"),
            cap_period=CapPeriod(spec.get("cap_period", "none")),
            postpaid=spec.get("postpaid", True),
            proof_requirements=spec.get("proof_requirements"),
            direct_costs_pyg=int(spec.get("direct_costs_pyg", 0)),
            notes=spec.get("notes"),
        )
        session.add(contract)
        session.flush()

        if spec.get("partner_token"):
            user = PartnerUser(
                id=new_id("partner_user"),
                contract_id=contract.id,
                company_id=company.id,
                full_name=spec.get("partner_name", "Responsable"),
                role=PartnerRole.MANAGER,
                token_hash=hash_token(spec["partner_token"]),
                is_active=True,
            )
            session.add(user)
            partner_users.append(user)

    ops = PartnerUser(
        id=new_id("partner_user"),
        contract_id=None,
        company_id=None,
        full_name=data.OPS_PARTNER["full_name"],
        role=PartnerRole(data.OPS_PARTNER["role"]),
        token_hash=hash_token(settings.demo_partner_token),
        is_active=True,
    )
    session.add(ops)
    session.flush()

    published = sum(
        1 for c in companies.values() if c.publication_status is PublicationStatus.PUBLISHED
    )

    return {
        "companies": len(companies),
        "published_companies": published,
        "categories": len(categories),
        "legal_entities": len(legal_entities),
        "contracts": len(data.CONTRACTS),
        "commission_rules": len(rules),
        "benefit_rules": len(data.BENEFIT_RULES),
        "partner_users": len(partner_users) + 1,
        "notice_es": data.DEMO_NOTICE_ES,
    }


def reseed_all(session: Session) -> dict[str, Any]:
    """Force rebuild of the demo dataset (dev only)."""
    return seed_all(session, force=True)
