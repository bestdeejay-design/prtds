"""PRTDS domain model — the shared commercial core (concept §13.1).

Every vertical (catalog, leads, commerce, loyalty, reservations, B2B) must reuse
these entities instead of inventing its own copy:

    Company / Brand / Branch / Offer / Contact / Consent / Lead /
    Attribution / Contract / Reward / Settlement

Entity separation required by §13.2:

    Company  ↔  Legal Entity  ↔  Brand  ↔  Branch

are four different things with their own identifiers and links. A "master
registry" row (legal entity) is a *source of data*, not a published card.

Provenance required by §13.2: every fact carries a source, an observation
timestamp, a verification level and an expiry policy — see :class:`FactMixin`.

Portability: no dialect-specific column types. Money = integer guaraníes,
rates = basis points (see app/core/money.py). Enums are stored as VARCHAR with a
CHECK constraint (``native_enum=False``) so migrations do not depend on
PostgreSQL ENUM objects.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.core.db import Base
from app.core.ids import new_id, utcnow


def _aware(value: datetime) -> datetime:
    """Normalise to timezone-aware UTC (SQLite returns naive datetimes)."""
    from datetime import timezone as _tz

    return value if value.tzinfo else value.replace(tzinfo=_tz.utc)


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class PublicationStatus(str, Enum):
    """staging → validation → moderation → publication pipeline (§13.2)."""

    DRAFT = "draft"
    STAGING = "staging"
    VALIDATED = "validated"
    MODERATED = "moderated"
    PUBLISHED = "published"
    ARCHIVED = "archived"

    @property
    def is_public(self) -> bool:
        return self is PublicationStatus.PUBLISHED


class VerificationLevel(str, Enum):
    UNVERIFIED = "unverified"
    SOURCE_ONLY = "source_only"
    PARTNER_CONFIRMED = "partner_confirmed"
    FIELD_VERIFIED = "field_verified"


class ChannelType(str, Enum):
    WHATSAPP = "whatsapp"
    PHONE = "phone"
    EMAIL = "email"
    WEBSITE = "website"
    INSTAGRAM = "instagram"
    WALK_IN = "walk_in"


class LeadIntent(str, Enum):
    WHATSAPP = "whatsapp"
    CALL = "call"
    BOOKING = "booking"
    REQUEST = "request"
    PURCHASE = "purchase"


class LeadStatus(str, Enum):
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    BOOKED = "booked"
    VISIT_DONE = "visit_done"
    SALE_CONFIRMED = "sale_confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ConsentPurpose(str, Enum):
    LEAD_TRANSFER = "lead_transfer"
    ANALYTICS = "analytics"
    MARKETING = "marketing"
    REMINDERS = "reminders"


class ActorKind(str, Enum):
    ANONYMOUS = "anonymous"
    USER = "user"
    PARTNER = "partner"
    AGENT = "agent"
    SYSTEM = "system"


class ContractStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class BillingModel(str, Enum):
    CPA = "cpa"  # per confirmed action / sale
    CPL = "cpl"  # per qualified lead
    REV_SHARE = "rev_share"  # % of the seller's transaction amount
    FIXED_FEE = "fixed_fee"  # service work (catalog enrichment, integration)


class CapPeriod(str, Enum):
    NONE = "none"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class SettlementStatus(str, Enum):
    #: commission calculated, waiting for the partner's reconciliation
    PENDING = "pending"
    #: partner confirmed, ready to invoice
    APPROVED = "approved"
    #: violates the hard rule of §10: contribution margin <= 0
    FLAGGED_NEGATIVE_CM = "flagged_negative_cm"
    #: no active contract => no commission may arise (§06: never "per click")
    NO_CONTRACT_BASIS = "no_contract_basis"
    DISPUTED = "disputed"
    VOID = "void"
    PAID = "paid"


class AvailabilityStatus(str, Enum):
    IN_STOCK = "in_stock"
    ON_REQUEST = "on_request"
    OUT_OF_STOCK = "out_of_stock"
    SEASONAL = "seasonal"


class PartnerRole(str, Enum):
    OWNER = "owner"
    MANAGER = "manager"
    AGENT = "agent"


def _enum(enum_cls: type[Enum], name: str | None = None, length: int = 32):
    """VARCHAR-backed enum column (portable across SQLite and PostgreSQL)."""
    return SAEnum(
        enum_cls,
        name=name or enum_cls.__name__.lower(),
        native_enum=False,
        length=length,
        validate_strings=True,
    )


# --------------------------------------------------------------------------- #
# Mixins
# --------------------------------------------------------------------------- #
class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class FactMixin:
    """Provenance for a *fact* (§13.2).

    A fact without a source and an observation time must not be published as
    truth; ``valid_until`` implements the staleness policy.
    """

    source_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_level: Mapped[VerificationLevel] = mapped_column(
        _enum(VerificationLevel), default=VerificationLevel.UNVERIFIED, nullable=False
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    @declared_attr
    def source(cls) -> Mapped["Source | None"]:  # noqa: N805
        """Relationship to the provenance record (must be a declared_attr in a mixin)."""
        return relationship("Source", foreign_keys=[cls.source_id])

    def is_stale(self, now: datetime | None = None) -> bool:
        now = now or utcnow()
        if self.valid_until is None:
            return False
        valid_until = _aware(self.valid_until)
        return valid_until < _aware(now)


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #
class Source(Base, TimestampMixin):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("source"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    license_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    trusted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


# --------------------------------------------------------------------------- #
# Catalog: legal entity / brand / category / company / branch / contact / offer
# --------------------------------------------------------------------------- #
class LegalEntity(Base, TimestampMixin, FactMixin):
    """A juridical person from the master registry.

    §12: ~156 354 legal entities in ``legal_entities`` are *data sources*, not
    156 thousand published cards. This table must never be used directly as a
    public listing.
    """

    __tablename__ = "legal_entities"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: new_id("legal_entity")
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    ruc: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True, index=True)
    country: Mapped[str] = mapped_column(String(2), default="PY", nullable=False)
    legal_form: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    companies: Mapped[list["Company"]] = relationship(back_populates="legal_entity")


class Brand(Base, TimestampMixin, FactMixin):
    __tablename__ = "brands"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("brand"))
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    legal_entity_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("legal_entities.id", ondelete="SET NULL"), nullable=True
    )
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    legal_entity: Mapped[LegalEntity | None] = relationship()


class Category(Base, TimestampMixin):
    """Configurable catalogue taxonomy.

    The catalogue is universal: categories are *data*, not code, so the team (or
    a partner) can add a branch of the tree without a deploy. ``default_intent``
    tells the card which primary action to offer (WhatsApp / call / booking /
    request) — §02 "clear actions on a narrow screen".
    """

    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: new_id("category")
    )
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    name_es: Mapped[str] = mapped_column(String(160), nullable=False)
    name_ru: Mapped[str | None] = mapped_column(String(160), nullable=True)
    description_es: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("categories.id", ondelete="CASCADE"), nullable=True, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    default_intent: Mapped[LeadIntent] = mapped_column(
        _enum(LeadIntent), default=LeadIntent.WHATSAPP, nullable=False
    )
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: search vocabulary is data: ["pelo", "cabello", "tijera"] — editable at
    #: runtime through the admin API, no deploy needed.
    synonyms_es: Mapped[list | None] = mapped_column(JSON, nullable=True)

    parent: Mapped["Category | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["Category"]] = relationship(back_populates="parent")


class Company(Base, TimestampMixin, FactMixin):
    """The public catalogue card (not the legal entity, not the brand)."""

    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: new_id("company")
    )
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    search_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: accent-folded, lower-cased search blob (name + brand + categories +
    #: barrios + offer titles). Maintained by catalog.refresh_search_text().
    search_text_norm: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    short_description_es: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description_es: Mapped[str | None] = mapped_column(Text, nullable=True)

    brand_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("brands.id", ondelete="SET NULL"), nullable=True, index=True
    )
    legal_entity_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("legal_entities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    primary_category_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )

    publication_status: Mapped[PublicationStatus] = mapped_column(
        _enum(PublicationStatus), default=PublicationStatus.DRAFT, nullable=False, index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Advertising must be labelled and must not masquerade as the objectively
    # best offer (§13.4).
    is_promoted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    promotion_label_es: Mapped[str] = mapped_column(
        String(60), default="Publicidad", nullable=False
    )
    promoted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: data-quality counters (contacts verified, hours fresh, duplicates, …)
    quality: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    brand: Mapped[Brand | None] = relationship()
    legal_entity: Mapped[LegalEntity | None] = relationship(back_populates="companies")
    primary_category: Mapped[Category | None] = relationship()
    branches: Mapped[list["Branch"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    offers: Mapped[list["Offer"]] = relationship(back_populates="company")
    category_links: Mapped[list["CompanyCategory"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    contracts: Mapped[list["Contract"]] = relationship(back_populates="company")

    __table_args__ = (
        Index("ix_companies_status_category", "publication_status", "primary_category_id"),
    )


class CompanyCategory(Base):
    __tablename__ = "company_categories"

    company_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True
    )

    company: Mapped[Company] = relationship(back_populates="category_links")
    category: Mapped[Category] = relationship()


class Branch(Base, TimestampMixin, FactMixin):
    """A physical/local point of sale: address, barrio, hours, channels."""

    __tablename__ = "branches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("branch"))
    company_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name_es: Mapped[str] = mapped_column(String(200), nullable=False)
    address_text: Mapped[str | None] = mapped_column(String(300), nullable=True)
    barrio: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    city: Mapped[str] = mapped_column(String(120), default="Asunción", nullable=False, index=True)
    district: Mapped[str | None] = mapped_column(String(120), nullable=True)

    #: Stored as plain coordinates for portability. Production migration path:
    #: add a PostGIS ``geography`` column + GiST index (docs/architecture.md).
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6, asdecimal=False), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 6, asdecimal=False), nullable=True)

    phone_e164: Mapped[str | None] = mapped_column(String(32), nullable=True)
    whatsapp_e164: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    instagram_handle: Mapped[str | None] = mapped_column(String(120), nullable=True)

    #: {"mon": [["09:00","12:00"], ["15:00","20:00"]], …}
    opening_hours: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    pickup_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    delivery_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    delivery_zone_es: Mapped[str | None] = mapped_column(String(300), nullable=True)
    delivery_fee_pyg: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    publication_status: Mapped[PublicationStatus] = mapped_column(
        _enum(PublicationStatus), default=PublicationStatus.DRAFT, nullable=False, index=True
    )

    company: Mapped[Company] = relationship(back_populates="branches")
    contacts: Mapped[list["Contact"]] = relationship(
        back_populates="branch", cascade="all, delete-orphan"
    )
    offers: Mapped[list["Offer"]] = relationship(back_populates="branch")


class Contact(Base, TimestampMixin, FactMixin):
    """A single verified channel of a branch (§13.1 shared ``Contact``)."""

    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: new_id("contact")
    )
    branch_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[ChannelType] = mapped_column(_enum(ChannelType), nullable=False)
    value: Mapped[str] = mapped_column(String(300), nullable=False)
    label_es: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    branch: Mapped[Branch] = relationship(back_populates="contacts")

    __table_args__ = (UniqueConstraint("branch_id", "channel", "value", name="uq_contact_value"),)


class Offer(Base, TimestampMixin, FactMixin):
    """A public offer of a *branch* for a *product/service position*.

    "In stock / available" is an assertion that requires a source and an expiry
    (§09), hence ``FactMixin`` + ``availability_status``.
    """

    __tablename__ = "offers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("offer"))
    company_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    branch_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("branches.id", ondelete="CASCADE"), nullable=True, index=True
    )
    category_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )

    sku: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    title_es: Mapped[str] = mapped_column(String(300), nullable=False)
    description_es: Mapped[str | None] = mapped_column(Text, nullable=True)

    currency: Mapped[str] = mapped_column(String(3), default="PYG", nullable=False)
    #: integer guaraníes — PYG has no fractional units
    base_price: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: seller's own on-counter discount, already known and confirmed
    seller_discount: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)

    availability_status: Mapped[AvailabilityStatus] = mapped_column(
        _enum(AvailabilityStatus), default=AvailabilityStatus.ON_REQUEST, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    #: normalizing layer fields (§09): brand/size/weight/pack — kept as JSON so
    #: that the catalogue stays universal across categories.
    attributes: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    company: Mapped[Company] = relationship(back_populates="offers")
    branch: Mapped[Branch | None] = relationship(back_populates="offers")
    category: Mapped[Category | None] = relationship()


# --------------------------------------------------------------------------- #
# Discount / cashback rules (deterministic engine, §08.2 — never invented by AI)
# --------------------------------------------------------------------------- #
class BenefitRule(Base, TimestampMixin, FactMixin):
    """One rule of one benefit source (§08.1: store card, bank cashback,
    manufacturer promo, PRTDS programme).

    Applied by a **server-side deterministic engine**; the result must record
    provenance (who supplied the rule, when it was updated, what it covers).
    """

    __tablename__ = "benefit_rules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rule"))
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    source_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="seller"
    )  # seller | bank | manufacturer | prtds | partner_affiliation
    financier: Mapped[str] = mapped_column(String(200), nullable=False)
    presentation_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="promo_code"
    )  # promo_code | membership | partner_affiliation | referral_code | bank_card
    company_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    category_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("categories.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="percent")
    # percent | fixed | cashback_percent
    value_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fixed_amount_pyg: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cap_amount_pyg: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: conditional = depends on bank/personal limits PRTDS does not know (§08.2)
    is_conditional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    guaranteed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    conditions_es: Mapped[str | None] = mapped_column(Text, nullable=True)
    stackable_with: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    company: Mapped[Company | None] = relationship()
    category: Mapped[Category | None] = relationship()


# --------------------------------------------------------------------------- #
# Consent (must precede transferring contacts to the seller — §13.4)
# --------------------------------------------------------------------------- #
class Consent(Base, TimestampMixin):
    __tablename__ = "consents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("consent"))
    subject_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="anonymous")
    #: hashed, never raw (§13.4: children/health/payment data need extra care)
    subject_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    purpose: Mapped[ConsentPurpose] = mapped_column(_enum(ConsentPurpose), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text_version: Mapped[str] = mapped_column(String(32), default="v1", nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    @property
    def is_valid(self) -> bool:
        return self.granted and self.revoked_at is None


# --------------------------------------------------------------------------- #
# Funnel events + attribution ledger (§07)
# --------------------------------------------------------------------------- #
class FunnelEvent(Base):
    """Append-only ledger of funnel events.

    Each row carries: unambiguous id, type, source, campaign, consent, timestamp
    and a causal link to a lead/contract (§13.4). ``idempotency_key`` is UNIQUE —
    one purchase must never generate two commissions.
    """

    __tablename__ = "funnel_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("event"))
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    company_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    branch_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("branches.id", ondelete="SET NULL"), nullable=True
    )
    offer_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("offers.id", ondelete="SET NULL"), nullable=True
    )
    lead_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    contract_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )

    actor_kind: Mapped[ActorKind] = mapped_column(
        _enum(ActorKind), default=ActorKind.ANONYMOUS, nullable=False
    )
    actor_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    session_ref: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    source: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    campaign_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    utm: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    consent_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("consents.id", ondelete="SET NULL"), nullable=True
    )

    #: money attached to a commissionable event (seller's GMV, not PRTDS revenue)
    amount_pyg: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    idempotency_key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    dedupe_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    disputed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    lead: Mapped["Lead | None"] = relationship(back_populates="events")
    company: Mapped[Company | None] = relationship()

    __table_args__ = (
        Index("ix_events_type_time", "event_type", "occurred_at"),
        Index("ix_events_company_type", "company_id", "event_type"),
    )


class Lead(Base, TimestampMixin):
    """A delivered request (``lead_submitted``) and its CRM lifecycle."""

    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("lead"))
    ref_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)

    company_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    branch_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("branches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    offer_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("offers.id", ondelete="SET NULL"), nullable=True
    )
    category_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )

    intent: Mapped[LeadIntent] = mapped_column(_enum(LeadIntent), nullable=False)
    status: Mapped[LeadStatus] = mapped_column(
        _enum(LeadStatus), default=LeadStatus.SUBMITTED, nullable=False, index=True
    )

    #: contact payload — stored only with a valid consent (§13.4)
    customer_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    customer_phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    prefilled_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[str | None] = mapped_column(String(160), nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    consent_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("consents.id", ondelete="SET NULL"), nullable=True
    )
    source_event_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    campaign_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    utm: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    channel: Mapped[str | None] = mapped_column(String(64), nullable=True)

    idempotency_key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rejection_reason_es: Mapped[str | None] = mapped_column(String(300), nullable=True)
    partner_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: confirmed commercial result (seller's amount, not PRTDS revenue)
    confirmed_amount_pyg: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    proof_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)

    events: Mapped[list[FunnelEvent]] = relationship(back_populates="lead")
    company: Mapped[Company] = relationship()
    branch: Mapped[Branch | None] = relationship()
    offer: Mapped[Offer | None] = relationship()
    consent: Mapped[Consent | None] = relationship()
    attributions: Mapped[list["LeadAttribution"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )
    settlements: Mapped[list["Settlement"]] = relationship(back_populates="lead")


class LeadAttribution(Base, TimestampMixin):
    """Attribution ledger entry: which channel/campaign gets credit (§07).

    Requires: transition source, campaign id, user consent, UTM/QR, a short
    attribution window, de-duplication, independent confirmation and the ability
    to dispute.
    """

    __tablename__ = "lead_attributions"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: new_id("attribution")
    )
    lead_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    campaign_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    method: Mapped[str] = mapped_column(
        String(32), nullable=False, default="utm"
    )  # utm | qr | manual_reconciliation | partner_report | direct
    window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    evidence_event_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    disputed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    lead: Mapped[Lead] = relationship(back_populates="attributions")


# --------------------------------------------------------------------------- #
# Contracts, commission rules, settlements (§10)
# --------------------------------------------------------------------------- #
class CommissionRule(Base, TimestampMixin):
    __tablename__ = "commission_rules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rule"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scope: Mapped[str] = mapped_column(String(24), nullable=False, default="company")
    # company | category | global
    company_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    category_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("categories.id", ondelete="CASCADE"), nullable=True, index=True
    )
    applies_to: Mapped[str] = mapped_column(String(40), nullable=False, default="sale_confirmed")
    rate_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fixed_amount_pyg: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    min_amount_pyg: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    max_amount_per_event_pyg: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    company: Mapped[Company | None] = relationship()
    category: Mapped[Category | None] = relationship()


class Contract(Base, TimestampMixin):
    """The only thing that determines what the business pays for (§06)."""

    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: new_id("contract")
    )
    company_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    counterparty_name: Mapped[str] = mapped_column(String(300), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[ContractStatus] = mapped_column(
        _enum(ContractStatus), default=ContractStatus.DRAFT, nullable=False, index=True
    )
    billing_model: Mapped[BillingModel] = mapped_column(_enum(BillingModel), nullable=False)
    commission_rule_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("commission_rules.id", ondelete="SET NULL"), nullable=True
    )
    currency: Mapped[str] = mapped_column(String(3), default="PYG", nullable=False)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attribution_window_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    cap_amount_pyg: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cap_period: Mapped[CapPeriod] = mapped_column(
        _enum(CapPeriod), default=CapPeriod.NONE, nullable=False
    )
    postpaid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: what proof the partner must supply for a confirmed result
    proof_requirements: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: standard variable costs used for the contribution-margin check (§10)
    direct_costs_pyg: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    company: Mapped[Company] = relationship(back_populates="contracts")
    commission_rule: Mapped[CommissionRule | None] = relationship()
    partner_users: Mapped[list["PartnerUser"]] = relationship(back_populates="contract")
    settlements: Mapped[list["Settlement"]] = relationship(back_populates="contract")

    def is_active_at(self, when: datetime) -> bool:
        if self.status is not ContractStatus.ACTIVE:
            return False
        from datetime import timezone as _tz

        def aware(value: datetime | None) -> datetime | None:
            if value is None:
                return None
            return value if value.tzinfo else value.replace(tzinfo=_tz.utc)

        start, end = aware(self.valid_from), aware(self.valid_to)
        when_aware = when if when.tzinfo else when.replace(tzinfo=_tz.utc)
        if start and when_aware < start:
            return False
        if end and when_aware > end:
            return False
        return True


class Settlement(Base, TimestampMixin):
    """The commission basis record (§10, §14 "основание комиссии").

    A row is created for every confirmed commercial result. If there is no
    active contract the row is recorded with status ``NO_CONTRACT_BASIS`` and
    **zero** commission: a click never creates a commission (§06).
    """

    __tablename__ = "settlements"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: new_id("settlement")
    )
    #: UNIQUE — one confirmed result may never produce two commissions (§13.4)
    idempotency_key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    lead_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("funnel_events.id", ondelete="SET NULL"), nullable=True
    )
    contract_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rule_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("commission_rules.id", ondelete="SET NULL"), nullable=True
    )
    company_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    basis_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="sale_confirmed")
    #: seller's transaction amount (GMV) — NOT PRTDS revenue
    basis_amount_pyg: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rate_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fixed_amount_pyg: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: PRTDS revenue for this operation
    commission_amount_pyg: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cap_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: variable costs (AI, payments, support, delivery, partner payouts)
    direct_costs_pyg: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    prtds_funded_discount_pyg: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    contribution_margin_pyg: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    currency: Mapped[str] = mapped_column(String(3), default="PYG", nullable=False)
    status: Mapped[SettlementStatus] = mapped_column(
        _enum(SettlementStatus, length=40),
        default=SettlementStatus.PENDING,
        nullable=False,
        index=True,
    )
    status_reason_es: Mapped[str | None] = mapped_column(String(300), nullable=True)
    proof_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    period_key: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    lead: Mapped[Lead | None] = relationship(back_populates="settlements")
    contract: Mapped[Contract | None] = relationship(back_populates="settlements")
    rule: Mapped[CommissionRule | None] = relationship()


class PartnerUser(Base, TimestampMixin):
    """A person allowed to reconcile leads on the partner side.

    Dev-only bearer token (hashed). Production must use real identity and role
    separation (§13.4); the token is never stored in documents or the repo.
    """

    __tablename__ = "partner_users"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: new_id("partner_user")
    )
    contract_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    company_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[PartnerRole] = mapped_column(
        _enum(PartnerRole), default=PartnerRole.MANAGER, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    contract: Mapped[Contract | None] = relationship(back_populates="partner_users")
    company: Mapped[Company | None] = relationship()


__all__ = [
    "ActorKind",
    "AvailabilityStatus",
    "Base",
    "BenefitRule",
    "BillingModel",
    "Brand",
    "Branch",
    "CapPeriod",
    "Category",
    "ChannelType",
    "Company",
    "CompanyCategory",
    "CommissionRule",
    "Consent",
    "ConsentPurpose",
    "Contact",
    "Contract",
    "ContractStatus",
    "FunnelEvent",
    "Lead",
    "LeadAttribution",
    "LeadIntent",
    "LeadStatus",
    "LegalEntity",
    "Offer",
    "PartnerRole",
    "PartnerUser",
    "PublicationStatus",
    "Settlement",
    "SettlementStatus",
    "Source",
    "VerificationLevel",
]
