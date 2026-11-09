"""Catalogue module: universal directory with a configurable taxonomy.

Product decisions implemented here (concept references):

* §01/§05 — one shared registry of companies and offers, no per-vertical copies.
* §02 — every card must work on a narrow screen, load fast on mobile internet
  and expose clear actions: WhatsApp, call, route, site, offer, booking.
* §09 — a company / brand / branch / offer are different things; "available"
  is an assertion that needs a source and an expiry date.
* §13.2 — only ``published`` records leave the staging → validation →
  moderation → publication pipeline. A row in the master registry is *not* a
  published card.
* §13.4 — advertising is labelled and never presented as the objectively best
  offer, so sponsored results are returned in a separate block.

The catalogue is universal: categories are data (``Category`` table) and can be
created at runtime through ``POST /api/admin/categories``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.ids import new_id, utcnow
from app.core.money import EffectivePrice, apply_bps, format_pyg
from app.core.text import fold
from app.modules import funnel as funnel_service
from app.domain.models import (
    BenefitRule,
    Branch,
    Category,
    Company,
    CompanyCategory,
    Contact,
    LeadIntent,
    Offer,
    PublicationStatus,
    VerificationLevel,
)

#: how many offers are embedded in a search result / card before pagination
OFFERS_PREVIEW = 6

_VERIFICATION_WEIGHT = {
    VerificationLevel.FIELD_VERIFIED: 15,
    VerificationLevel.PARTNER_CONFIRMED: 10,
    VerificationLevel.SOURCE_ONLY: 5,
    VerificationLevel.UNVERIFIED: 0,
}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    value = _aware(value)
    return value.isoformat() if value else None


# --------------------------------------------------------------------------- #
# Categories
# --------------------------------------------------------------------------- #
def category_by_slug(session: Session, slug: str) -> Category | None:
    return session.scalar(select(Category).where(Category.slug == slug))


def descendant_slugs(session: Session, slug: str) -> list[str]:
    """A category filter always includes its children (tree taxonomy)."""
    root = category_by_slug(session, slug)
    if root is None:
        return [slug]
    all_categories = list(session.scalars(select(Category)).all())
    by_parent: dict[str | None, list[Category]] = {}
    for cat in all_categories:
        by_parent.setdefault(cat.parent_id, []).append(cat)

    collected: list[str] = []
    stack = [root]
    while stack:
        current = stack.pop()
        collected.append(current.slug)
        stack.extend(by_parent.get(current.id, []))
    return collected


def categories_tree(session: Session, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    stmt = select(Category).order_by(Category.sort_order, Category.name_es)
    if not include_inactive:
        stmt = stmt.where(Category.is_active.is_(True))
    rows = list(session.scalars(stmt).all())

    # A company belongs to a category either as its primary one or through a
    # link row — in the demo dataset it is always both, so summing the two
    # sources counted every card twice: the chip promised "Gastronomía 7" and
    # the search then returned 3. The badge is a set of distinct companies.
    companies_by_category: dict[str, set[str]] = {}

    def _add(category_id: str | None, company_id: str) -> None:
        if not category_id:
            return
        companies_by_category.setdefault(category_id, set()).add(company_id)

    for category_id, company_id in session.execute(
        select(CompanyCategory.category_id, CompanyCategory.company_id)
        .join(Company, Company.id == CompanyCategory.company_id)
        .where(Company.publication_status == PublicationStatus.PUBLISHED)
    ).all():
        _add(category_id, company_id)

    for category_id, company_id in session.execute(
        select(Company.primary_category_id, Company.id).where(
            Company.publication_status == PublicationStatus.PUBLISHED
        )
    ).all():
        _add(category_id, company_id)

    by_parent: dict[str | None, list[Category]] = {}
    for cat in rows:
        by_parent.setdefault(cat.parent_id, []).append(cat)

    def subtree_ids(cat: Category) -> list[str]:
        collected = [cat.id]
        for child in by_parent.get(cat.id, []):
            collected.extend(subtree_ids(child))
        return collected

    def own_count(cat: Category) -> int:
        return len(companies_by_category.get(cat.id, set()))

    def subtree_count(cat: Category) -> int:
        merged: set[str] = set()
        for category_id in subtree_ids(cat):
            merged |= companies_by_category.get(category_id, set())
        return len(merged)

    def serialize(cat: Category) -> dict[str, Any]:
        children = [serialize(child) for child in by_parent.get(cat.id, [])]
        # a parent reports the distinct companies of its whole subtree: a card
        # tagged in two child categories is counted once, and the number on the
        # chip equals the number of cards the search will actually return
        company_count = subtree_count(cat)
        return {
            "id": cat.id,
            "slug": cat.slug,
            "name_es": cat.name_es,
            "name_ru": cat.name_ru,
            "description_es": cat.description_es,
            "icon": cat.icon,
            "default_intent": cat.default_intent.value,
            "is_active": cat.is_active,
            "sort_order": cat.sort_order,
            "published_companies": company_count,
            "published_companies_own": own_count(cat),
            "children": children,
        }

    return [serialize(cat) for cat in by_parent.get(None, [])]


def create_category(session: Session, payload: dict[str, Any]) -> Category:
    slug = payload["slug"]
    if category_by_slug(session, slug) is not None:
        raise ValueError(f"la categoría '{slug}' ya existe")

    parent: Category | None = None
    if payload.get("parent_slug"):
        parent = category_by_slug(session, payload["parent_slug"])
        if parent is None:
            raise ValueError(f"categoría padre desconocida: {payload['parent_slug']}")

    category = Category(
        id=new_id("category"),
        slug=slug,
        name_es=payload["name_es"],
        name_ru=payload.get("name_ru"),
        description_es=payload.get("description_es"),
        parent_id=parent.id if parent else None,
        sort_order=payload.get("sort_order", 100),
        default_intent=LeadIntent(payload.get("default_intent", LeadIntent.WHATSAPP.value)),
        icon=payload.get("icon"),
        is_active=payload.get("is_active", True),
    )
    session.add(category)
    session.flush()
    return category


def update_category(session: Session, slug: str, payload: dict[str, Any]) -> Category:
    category = category_by_slug(session, slug)
    if category is None:
        raise LookupError(f"categoría desconocida: {slug}")

    if "parent_slug" in payload:
        parent_slug = payload["parent_slug"]
        if parent_slug in (None, ""):
            category.parent_id = None
        else:
            parent = category_by_slug(session, parent_slug)
            if parent is None:
                raise LookupError(f"categoría padre desconocida: {parent_slug}")
            if parent.id == category.id:
                raise ValueError("una categoría no puede ser padre de sí misma")
            category.parent_id = parent.id

    for field in ("name_es", "name_ru", "description_es", "sort_order", "icon", "is_active"):
        if field in payload and payload[field] is not None:
            setattr(category, field, payload[field])
    if payload.get("default_intent"):
        category.default_intent = LeadIntent(payload["default_intent"])

    session.flush()
    return category


# --------------------------------------------------------------------------- #
# Effective price (§09) — deterministic, server-side, never invented by AI
# --------------------------------------------------------------------------- #
_RULE_PRIORITY = {"seller": 0, "manufacturer": 1, "bank": 2, "prtds": 3, "partner_affiliation": 4}
#: hard limit on stacking guaranteed benefits (no unlimited stacking — §08.2)
MAX_STACKED_GUARANTEED = 2


def applicable_rules(session: Session, offer: Offer) -> list[BenefitRule]:
    now = utcnow()
    stmt = (
        select(BenefitRule)
        .where(BenefitRule.is_active.is_(True))
        .where(or_(BenefitRule.company_id.is_(None), BenefitRule.company_id == offer.company_id))
        .where(or_(BenefitRule.category_id.is_(None), BenefitRule.category_id == offer.category_id))
    )
    rules = [
        rule
        for rule in session.scalars(stmt).all()
        if (rule.valid_until is None or _aware(rule.valid_until) >= now)
        and (rule.valid_from is None or _aware(rule.valid_from) <= now)
    ]
    rules.sort(key=lambda r: (_RULE_PRIORITY.get(r.source_kind, 9), -r.value_bps, r.code))
    return rules


def compute_effective_price(
    session: Session,
    offer: Offer,
    *,
    branch: Branch | None = None,
    delivery_mode: str = "pickup",
) -> EffectivePrice:
    """base − seller discount − confirmed benefits + delivery/pickup fee.

    Conditional bank cashback is reported separately as *potential* and is not
    folded into the guaranteed total (§08.2, §09).
    """
    rules = applicable_rules(session, offer)

    seller_discount = int(offer.seller_discount or 0)
    confirmed_benefits = 0
    provenance: list[str] = []
    stacked = 0
    conditional_rules: list[BenefitRule] = []

    # 1st pass — guaranteed, non-conditional benefits only (max stacking applies).
    for rule in rules:
        if rule.is_conditional or not rule.guaranteed:
            conditional_rules.append(rule)
            continue
        if stacked >= MAX_STACKED_GUARANTEED:
            provenance.append(f"{rule.code}:no_apilado")
            continue
        amount = (
            apply_bps(offer.base_price, rule.value_bps)
            if rule.kind == "percent"
            else int(rule.fixed_amount_pyg)
        )
        if rule.cap_amount_pyg:
            amount = min(amount, rule.cap_amount_pyg)
        confirmed_benefits += amount
        stacked += 1
        provenance.append(f"{rule.code}:{rule.source_kind}:aplicado")

    # 2nd pass — conditional bank cashback is computed on what the buyer would
    # actually pay and reported separately: it depends on bank rules and on a
    # personal monthly limit PRTDS does not know (§08.2).
    net_before_cashback = max(int(offer.base_price) - seller_discount - confirmed_benefits, 0)
    potential_cashback = 0
    for rule in conditional_rules:
        if rule.kind != "cashback_percent":
            provenance.append(f"{rule.code}:no_aplicable")
            continue
        amount = apply_bps(net_before_cashback, rule.value_bps)
        if rule.cap_amount_pyg:
            amount = min(amount, rule.cap_amount_pyg)
        potential_cashback += amount
        provenance.append(f"{rule.code}:{rule.source_kind}:condicional")

    delivery_fee = 0
    pickup_fee = 0
    if branch is not None and delivery_mode == "delivery" and branch.delivery_available:
        delivery_fee = int(branch.delivery_fee_pyg or 0)

    return EffectivePrice(
        currency=offer.currency,
        base_price=int(offer.base_price),
        seller_discount=seller_discount,
        confirmed_benefits=confirmed_benefits,
        delivery_fee=delivery_fee,
        pickup_fee=pickup_fee,
        potential_cashback=potential_cashback,
        potential_cashback_conditional=True,
        rule_provenance=provenance,
    )


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #
def serialize_offer(session: Session, offer: Offer, *, branch: Branch | None = None) -> dict[str, Any]:
    price = compute_effective_price(session, offer, branch=branch or offer.branch)
    return {
        "id": offer.id,
        "title_es": offer.title_es,
        "description_es": offer.description_es,
        "sku": offer.sku,
        "barcode": offer.barcode,
        "unit": offer.unit,
        "currency": offer.currency,
        "availability_status": offer.availability_status.value,
        "price": price.as_dict(),
        "price_display": format_pyg(price.effective_total),
        "base_price_display": format_pyg(price.base_price),
        "attributes": offer.attributes or {},
        "freshness": {
            "observed_at": _iso(offer.observed_at),
            "valid_until": _iso(offer.valid_until),
            "is_stale": offer.is_stale(),
            "verification_level": offer.verification_level.value,
            "source": offer.source.name if offer.source else None,
        },
    }


def _primary_contact(branch: Branch, channel: str) -> Contact | None:
    matches = [c for c in branch.contacts if c.channel.value == channel]
    if not matches:
        return None
    return next((c for c in matches if c.is_primary), matches[0])


def serialize_branch(session: Session, branch: Branch) -> dict[str, Any]:
    whatsapp = branch.whatsapp_e164 or (_primary_contact(branch, "whatsapp") or Contact()).value
    phone = branch.phone_e164 or (_primary_contact(branch, "phone") or Contact()).value
    return {
        "id": branch.id,
        "name_es": branch.name_es,
        "address_text": branch.address_text,
        "barrio": branch.barrio,
        "city": branch.city,
        "district": branch.district,
        "latitude": branch.latitude,
        "longitude": branch.longitude,
        "map_url": (
            f"https://www.openstreetmap.org/?mlat={branch.latitude}&mlon={branch.longitude}#map=17/"
            f"{branch.latitude}/{branch.longitude}"
            if branch.latitude is not None and branch.longitude is not None
            else None
        ),
        "channels": {
            "whatsapp": whatsapp,
            "phone": phone,
            "email": branch.email,
            "website": branch.website_url,
            "instagram": branch.instagram_handle,
        },
        "contacts": [
            {
                "id": c.id,
                "channel": c.channel.value,
                "value": c.value,
                "label_es": c.label_es,
                "is_primary": c.is_primary,
                "verified_at": _iso(c.verified_at),
                "verification_level": c.verification_level.value,
            }
            for c in branch.contacts
        ],
        "opening_hours": branch.opening_hours or {},
        "pickup_available": branch.pickup_available,
        "delivery_available": branch.delivery_available,
        "delivery_zone_es": branch.delivery_zone_es,
        "delivery_fee_display": format_pyg(branch.delivery_fee_pyg) if branch.delivery_fee_pyg else None,
        "freshness": {
            "observed_at": _iso(branch.observed_at),
            "verified_at": _iso(branch.valid_from),
            "verification_level": branch.verification_level.value,
            "is_stale": branch.is_stale(),
            "source": branch.source.name if branch.source else None,
        },
    }


def serialize_company_summary(session: Session, company: Company, *, branch: Branch | None = None) -> dict[str, Any]:
    branches = [b for b in company.branches if b.publication_status.is_public]
    primary = branch or (branches[0] if branches else None)
    offers = [o for o in company.offers if o.is_active][:OFFERS_PREVIEW]
    min_price = min((int(o.base_price) for o in company.offers if o.is_active and o.base_price), default=None)

    return {
        "id": company.id,
        "slug": company.slug,
        "display_name": company.display_name,
        "short_description_es": company.short_description_es,
        "brand": company.brand.name if company.brand else None,
        "category": company.primary_category.name_es if company.primary_category else None,
        "category_slug": company.primary_category.slug if company.primary_category else None,
        "barrios": sorted({b.barrio for b in branches if b.barrio}),
        "cities": sorted({b.city for b in branches}),
        "branch_count": len(branches),
        "primary_branch": serialize_branch(session, primary) if primary else None,
        "offers_preview": [serialize_offer(session, o, branch=primary) for o in offers[:3]],
        "min_price_display": format_pyg(min_price) if min_price else None,
        "verification_level": company.verification_level.value,
        "is_promoted": bool(company.is_promoted),
        "promotion_label_es": company.promotion_label_es if company.is_promoted else None,
        "published_at": _iso(company.published_at),
        "url": f"/empresa/{company.slug}",
    }


def serialize_card(session: Session, company: Company) -> dict[str, Any]:
    branches = [b for b in company.branches if b.publication_status.is_public]
    category_ids = {link.category_id for link in company.category_links}
    if company.primary_category_id:
        category_ids.add(company.primary_category_id)
    categories = list(
        session.scalars(select(Category).where(Category.id.in_(category_ids or {"-"}))).all()
    )

    offers = [o for o in company.offers if o.is_active]
    offers.sort(key=lambda o: (o.availability_status.value != "in_stock", o.title_es))

    observed_dates = [
        _aware(d)
        for d in [company.observed_at, *(b.observed_at for b in branches), *(o.observed_at for o in offers)]
        if d
    ]

    return {
        "id": company.id,
        "slug": company.slug,
        "display_name": company.display_name,
        "short_description_es": company.short_description_es,
        "description_es": company.description_es,
        "brand": (
            {
                "id": company.brand.id,
                "name": company.brand.name,
                "slug": company.brand.slug,
                "logo_url": company.brand.logo_url,
            }
            if company.brand
            else None
        ),
        "legal_entity": (
            {
                "id": company.legal_entity.id,
                "name": company.legal_entity.name,
                "ruc": company.legal_entity.ruc,
                "note_es": "Persona jurídica del registro maestro; no es la ficha pública.",
            }
            if company.legal_entity
            else None
        ),
        "categories": [
            {"slug": c.slug, "name_es": c.name_es, "default_intent": c.default_intent.value}
            for c in sorted(categories, key=lambda c: c.sort_order)
        ],
        "primary_intent": (
            company.primary_category.default_intent.value
            if company.primary_category
            else LeadIntent.WHATSAPP.value
        ),
        "branches": [serialize_branch(session, b) for b in branches],
        "offers": [
            serialize_offer(session, o, branch=next((b for b in branches if b.id == o.branch_id), None))
            for o in offers
        ],
        "publication_status": company.publication_status.value,
        "published_at": _iso(company.published_at),
        "verification_level": company.verification_level.value,
        "quality": company.quality or {},
        "is_promoted": bool(company.is_promoted),
        "promotion_label_es": company.promotion_label_es if company.is_promoted else None,
        "data_freshness": {
            "last_observed_at": _iso(max(observed_dates) if observed_dates else None),
            "stale_offers": sum(1 for o in offers if o.is_stale()),
            "offers_total": len(offers),
            "source_note_es": (
                "Datos aportados por fuentes registradas; la disponibilidad y los precios "
                "requieren confirmación del vendedor."
            ),
        },
        "actions_es": {
            "whatsapp": "WhatsApp",
            "call": "Llamar",
            "route": "Cómo llegar",
            "website": "Sitio web",
            "request": "Enviar solicitud",
        },
    }


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
def _published_only(stmt: Select) -> Select:
    return stmt.where(Company.publication_status == PublicationStatus.PUBLISHED)


def _matches_query(company: Company, needle: str) -> int:
    """Relevance score.

    Deliberately simple and deterministic for the pilot dataset; matching is
    accent-insensitive because Spanish/Guaraní queries arrive without diacritics
    from phone keyboards. Production path (docs/architecture.md): PostgreSQL
    ``unaccent`` + ``tsvector`` with the Spanish configuration and ``pg_trgm``
    for typos; scoring then moves into SQL with a GIN index.
    """
    if not needle:
        return 10
    folded_needle = fold(needle)
    name = fold(company.display_name)
    haystack = fold(
        " ".join(
            filter(
                None,
                [
                    company.display_name,
                    company.search_text,
                    company.short_description_es,
                    company.brand.name if company.brand else "",
                    company.primary_category.name_es if company.primary_category else "",
                ],
            )
        )
    )
    score = 0
    if name == folded_needle:
        score += 120
    elif name.startswith(folded_needle):
        score += 90
    elif folded_needle in name:
        score += 60
    if folded_needle in haystack:
        score += 40
    tokens = folded_needle.split()
    matched_tokens = sum(1 for token in tokens if token and token in haystack)
    if tokens:
        score += int(25 * matched_tokens / len(tokens))
    if tokens and matched_tokens == len(tokens) and name.startswith(tokens[0]):
        score += 15
    score += _VERIFICATION_WEIGHT.get(company.verification_level, 0)
    published = _aware(company.published_at)
    if published and published >= utcnow() - timedelta(days=30):
        score += 5
    return score


def refresh_search_text(session: Session, company: Company) -> str:
    """Rebuild the search blob of one company (display text + folded index).

    Called after any change to the company, its categories, branches or offers.
    ``POST /api/admin/reindex`` recomputes the whole catalogue.
    """
    category_names: list[str] = []
    if company.primary_category:
        category_names.append(company.primary_category.name_es)
    category_names.extend(
        link.category.name_es for link in company.category_links if link.category is not None
    )

    parts: list[str | None] = [
        company.display_name,
        company.short_description_es,
        company.description_es,
        company.brand.name if company.brand else None,
        company.legal_entity.name if company.legal_entity else None,
        *category_names,
        *category_synonyms(session, company),
    ]
    for branch in company.branches:
        parts.extend([branch.name_es, branch.barrio, branch.city, branch.address_text])
        parts.extend(branch_capability_phrases(branch))
    for offer in company.offers:
        parts.extend([offer.title_es, offer.sku, offer.unit])

    company.search_text = " ".join(part for part in parts if part)
    company.search_text_norm = fold(company.search_text)
    session.flush()
    return company.search_text_norm


def category_synonyms(session: Session, company: Company) -> list[str]:
    """Search vocabulary of the categories a company belongs to."""
    category_ids = {link.category_id for link in company.category_links}
    if company.primary_category_id:
        category_ids.add(company.primary_category_id)
    if not category_ids:
        return []
    rows = session.scalars(select(Category).where(Category.id.in_(category_ids))).all()
    words: list[str] = []
    for row in rows:
        words.extend(row.synonyms_es or [])
    return words


def branch_capability_phrases(branch: Branch) -> list[str]:
    """Phrases people actually type that are not in any text field."""
    phrases: list[str] = []
    hours = branch.opening_hours or {}
    if hours.get("mon") == [["00:00", "23:59"]] and len(hours) >= 7:
        phrases.append("abierto 24 horas todos los dias turno noche urgencias")
    if branch.delivery_available:
        phrases.append("delivery entrega a domicilio envio")
    if branch.pickup_available:
        phrases.append("retiro en local recoger pickup")
    return phrases


def reindex_all(session: Session) -> int:
    companies = list(session.scalars(select(Company)).all())
    for company in companies:
        refresh_search_text(session, company)
    session.flush()
    return len(companies)


def search(
    session: Session,
    *,
    q: str | None = None,
    category_slug: str | None = None,
    barrio: str | None = None,
    city: str | None = None,
    channel: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    sort: str = "relevance",
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """Search published companies only.

    Sponsored results are returned in a separate labelled block so a paid
    position is never presented as the objectively best offer (§13.4).
    """
    page = max(page, 1)
    limit = max(1, min(limit, 50))
    needle = (q or "").strip().lower() or None

    stmt = _published_only(select(Company)).options(
        selectinload(Company.branches).selectinload(Branch.contacts),
        selectinload(Company.brand),
        selectinload(Company.primary_category),
        selectinload(Company.offers),
        selectinload(Company.category_links),
    )

    tokens = fold(needle).split() if needle else []
    if tokens:
        # every token must appear in the folded blob: "alquiler auto" finds
        # "Alquiler de autos económicos" even though the phrase never occurs.
        phrase = f"%{fold(needle)}%"
        stmt = stmt.where(
            or_(
                Company.search_text_norm.ilike(phrase),
                Company.display_name.ilike(f"%{needle}%"),
                and_(
                    *[Company.search_text_norm.ilike(f"%{token}%") for token in tokens]
                ),
            )
        )

    if category_slug:
        slugs = descendant_slugs(session, category_slug)
        cat_ids = list(session.scalars(select(Category.id).where(Category.slug.in_(slugs))).all())
        stmt = stmt.where(
            or_(
                Company.primary_category_id.in_(cat_ids or ["-"]),
                Company.id.in_(
                    select(CompanyCategory.company_id).where(
                        CompanyCategory.category_id.in_(cat_ids or ["-"])
                    )
                ),
            )
        )

    if barrio or city or channel:
        branch_stmt = select(Branch.company_id).where(Branch.publication_status == PublicationStatus.PUBLISHED)
        if barrio:
            branch_stmt = branch_stmt.where(Branch.barrio.ilike(f"%{barrio.strip()}%"))
        if city:
            branch_stmt = branch_stmt.where(Branch.city.ilike(f"%{city.strip()}%"))
        if channel == "whatsapp":
            branch_stmt = branch_stmt.where(Branch.whatsapp_e164.is_not(None))
        elif channel == "phone":
            branch_stmt = branch_stmt.where(Branch.phone_e164.is_not(None))
        elif channel == "delivery":
            branch_stmt = branch_stmt.where(Branch.delivery_available.is_(True))
        elif channel == "pickup":
            branch_stmt = branch_stmt.where(Branch.pickup_available.is_(True))
        stmt = stmt.where(Company.id.in_(branch_stmt))

    if min_price is not None or max_price is not None:
        offer_stmt = select(Offer.company_id).where(Offer.is_active.is_(True))
        if min_price is not None:
            offer_stmt = offer_stmt.where(Offer.base_price >= min_price)
        if max_price is not None:
            offer_stmt = offer_stmt.where(Offer.base_price <= max_price)
        stmt = stmt.where(Company.id.in_(offer_stmt))

    companies = list(session.scalars(stmt).all())

    # Каждая сортировка заканчивается именем и slug: без этого карточки с
    # одинаковой датой или ценой идут в порядке, который выбирает база, и
    # порядок плавает между запросами — на пагинации карточка могла бы
    # повториться на двух страницах или не попасть ни на одну.
    def _tiebreak(c: Company) -> tuple[str, str]:
        return (c.display_name.lower(), c.slug)

    scored = sorted(
        companies,
        key=lambda c: (
            -_matches_query(c, needle or ""),
            *_tiebreak(c),
        ),
    )
    if sort == "name":
        scored = sorted(companies, key=_tiebreak)
    elif sort == "recent":
        oldest = datetime.min.replace(tzinfo=timezone.utc)
        scored = sorted(
            companies,
            key=lambda c: (
                -(_aware(c.published_at) or oldest).timestamp(),
                *_tiebreak(c),
            ),
        )
    elif sort == "price_asc":
        def _min_price(c: Company) -> int:
            prices = [int(o.base_price) for o in c.offers if o.is_active and o.base_price]
            return min(prices) if prices else 10**15

        scored = sorted(companies, key=lambda c: (_min_price(c), *_tiebreak(c)))

    # A promoted card never occupies an organic ranking slot: it is shown only in
    # the labelled advertising block (§13.4). With a small catalogue this also
    # avoids the same company appearing twice on one screen.
    sponsored = [c for c in scored if c.is_promoted]
    organic = [c for c in scored if not c.is_promoted]

    total = len(organic)
    start = (page - 1) * limit
    window = organic[start : start + limit]

    return {
        "total_organic": len(organic),
        "total_sponsored": len(sponsored),
        "query": {
            "q": needle,
            "category": category_slug,
            "barrio": barrio,
            "city": city,
            "channel": channel,
            "min_price": min_price,
            "max_price": max_price,
            "sort": sort,
            "page": page,
            "limit": limit,
        },
        "total": total,
        "page_count": (total + limit - 1) // limit,
        "results": [serialize_company_summary(session, c) for c in window],
        "sponsored": {
            "label_es": "Publicidad",
            "note_es": "Posiciones contratadas. No equivalen a la mejor oferta objetiva.",
            "items": [serialize_company_summary(session, c) for c in sponsored[:3]],
        },
        "ranking_note_es": (
            "Orden por relevancia, verificación de datos y actualidad. "
            "La publicidad se muestra por separado y siempre etiquetada."
        ),
    }


def published_card(session: Session, slug: str) -> Company | None:
    company = session.scalar(
        _published_only(select(Company))
        .where(Company.slug == slug)
        .options(
            selectinload(Company.branches).selectinload(Branch.contacts),
            selectinload(Company.brand),
            selectinload(Company.legal_entity),
            selectinload(Company.primary_category),
            selectinload(Company.category_links),
            selectinload(Company.offers).selectinload(Offer.source),
        )
    )
    return company


def facets(session: Session) -> dict[str, Any]:
    """Filter facets built from published data only."""
    barrios = session.execute(
        select(Branch.barrio, func.count(Branch.id))
        .join(Company, Company.id == Branch.company_id)
        .where(Company.publication_status == PublicationStatus.PUBLISHED)
        .where(Branch.publication_status == PublicationStatus.PUBLISHED)
        .where(Branch.barrio.is_not(None))
        .group_by(Branch.barrio)
        .order_by(func.count(Branch.id).desc())
    ).all()
    cities = session.execute(
        select(Branch.city, func.count(Branch.id))
        .join(Company, Company.id == Branch.company_id)
        .where(Company.publication_status == PublicationStatus.PUBLISHED)
        .group_by(Branch.city)
        .order_by(func.count(Branch.id).desc())
    ).all()
    return {
        "barrios": [{"name": row[0], "count": int(row[1])} for row in barrios if row[0]],
        "cities": [{"name": row[0], "count": int(row[1])} for row in cities if row[0]],
        "channels": [
            {"code": "whatsapp", "label_es": "WhatsApp"},
            {"code": "phone", "label_es": "Llamada"},
            {"code": "delivery", "label_es": "Delivery"},
            {"code": "pickup", "label_es": "Retiro en local"},
        ],
        "sorts": [
            {"code": "relevance", "label_es": "Relevancia"},
            {"code": "name", "label_es": "Nombre A–Z"},
            {"code": "recent", "label_es": "Publicadas recientemente"},
            {"code": "price_asc", "label_es": "Precio más bajo"},
        ],
    }


def registry_vs_public(session: Session) -> dict[str, Any]:
    """The distinction §15 forbids to confuse: registry rows ≠ published cards."""
    from app.domain.models import LegalEntity

    legal_entities = session.scalar(select(func.count(LegalEntity.id))) or 0
    companies_total = session.scalar(select(func.count(Company.id))) or 0
    published = (
        session.scalar(
            select(func.count(Company.id)).where(
                Company.publication_status == PublicationStatus.PUBLISHED
            )
        )
        or 0
    )
    by_status = dict(
        session.execute(
            select(Company.publication_status, func.count(Company.id)).group_by(
                Company.publication_status
            )
        ).all()
    )
    return {
        "legal_entities_in_registry": int(legal_entities),
        "company_records_total": int(companies_total),
        "published_cards": int(published),
        "by_status": {
            (status.value if hasattr(status, "value") else str(status)): int(count)
            for status, count in by_status.items()
        },
        "warning_es": (
            "Personas jurídicas en el registro ≠ fichas publicadas y operativas."
        ),
    }


def log_search_impressions(
    session: Session,
    results: dict[str, Any],
    *,
    session_ref: str | None,
    actor_ref: str | None = None,
    source: str = "search",
    campaign_id: str | None = None,
    utm: dict | None = None,
) -> int:
    """Record ``search_result`` / ``view`` events for what was actually shown.

    Idempotent per 5-minute bucket, so refreshing a page does not inflate the
    funnel (§07).
    """
    from app.core.funnel import EventType

    shown = 0
    for item in list(results.get("results", [])) + list(
        results.get("sponsored", {}).get("items", [])
    ):
        funnel_service.record_event(
            session,
            EventType.SEARCH_RESULT,
            company_id=item["id"],
            actor_ref=actor_ref,
            session_ref=session_ref,
            source="sponsored" if item.get("is_promoted") else source,
            campaign_id=campaign_id,
            utm=utm,
            evidence={"q": results["query"].get("q"), "sort": results["query"].get("sort")},
        )
        shown += 1
    session.flush()
    return shown
