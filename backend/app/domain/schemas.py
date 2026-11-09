"""Pydantic v2 DTOs for every write operation.

Reads are serialised by small explicit functions in each module (dict output) so
that the API contract stays visible and greppable; writes always go through the
validated models below.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.models import (
    BillingModel,
    CapPeriod,
    ChannelType,
    ConsentPurpose,
    ContractStatus,
    LeadIntent,
    LeadStatus,
    PublicationStatus,
)

PYG = "PYG"


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# Categories — the catalogue is universal, the taxonomy is data (§ "vertical")
# --------------------------------------------------------------------------- #
class CategoryCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name_es: str = Field(min_length=2, max_length=160)
    name_ru: str | None = Field(default=None, max_length=160)
    description_es: str | None = Field(default=None, max_length=1000)
    parent_slug: str | None = Field(default=None, max_length=120)
    sort_order: int = Field(default=100, ge=0, le=10_000)
    default_intent: LeadIntent = LeadIntent.WHATSAPP
    icon: str | None = Field(default=None, max_length=64)
    synonyms_es: list[str] | None = Field(default=None, max_length=40)
    is_active: bool = True


class CategoryUpdate(BaseModel):
    name_es: str | None = Field(default=None, max_length=160)
    name_ru: str | None = Field(default=None, max_length=160)
    description_es: str | None = Field(default=None, max_length=1000)
    parent_slug: str | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)
    default_intent: LeadIntent | None = None
    icon: str | None = None
    synonyms_es: list[str] | None = Field(default=None, max_length=40)
    is_active: bool | None = None


# --------------------------------------------------------------------------- #
# Funnel events (§07, §13.4)
# --------------------------------------------------------------------------- #
class UTM(BaseModel):
    source: str | None = Field(default=None, max_length=64)
    medium: str | None = Field(default=None, max_length=64)
    campaign: str | None = Field(default=None, max_length=64)
    term: str | None = Field(default=None, max_length=64)
    content: str | None = Field(default=None, max_length=64)


class EventIngest(BaseModel):
    """Client-side event. The server, not the client, decides what it proves."""

    event_type: str = Field(min_length=3, max_length=40)
    company_slug: str | None = None
    branch_id: str | None = None
    offer_id: str | None = None
    lead_ref: str | None = None
    source: str | None = Field(default=None, max_length=64)
    campaign_id: str | None = Field(default=None, max_length=64)
    utm: UTM | None = None
    amount_pyg: int | None = Field(default=None, ge=0)
    idempotency_key: str | None = Field(default=None, max_length=64)

    @field_validator("event_type")
    @classmethod
    def _known(cls, value: str) -> str:
        from app.core.funnel import EventType

        try:
            return EventType(value).value
        except ValueError as exc:  # pragma: no cover - guarded by API docs
            allowed = ", ".join(e.value for e in EventType)
            raise ValueError(f"event_type desconocido. Permitidos: {allowed}") from exc


class ConsentIn(BaseModel):
    purpose: ConsentPurpose = ConsentPurpose.LEAD_TRANSFER
    granted: bool = True
    channel: str | None = Field(default=None, max_length=64)
    #: any stable pseudonymous reference; it is hashed before storage
    subject_ref: str | None = Field(default=None, max_length=120)


# --------------------------------------------------------------------------- #
# Leads (§06, §07)
# --------------------------------------------------------------------------- #
class WhatsAppLinkRequest(BaseModel):
    company_slug: str
    branch_id: str | None = None
    offer_id: str | None = None
    message: str | None = Field(default=None, max_length=900)
    campaign_id: str | None = Field(default=None, max_length=64)
    utm: UTM | None = None
    source: str | None = Field(default=None, max_length=64)


_PHONE_RE = re.compile(r"^\+?[0-9 ()\-]{6,24}$")


class LeadSubmit(BaseModel):
    company_slug: str
    branch_id: str | None = None
    offer_id: str | None = None
    intent: LeadIntent = LeadIntent.REQUEST
    customer_name: str | None = Field(default=None, max_length=160)
    customer_phone: str | None = Field(default=None, max_length=32)
    message: str | None = Field(default=None, max_length=2000)
    requested_at: str | None = Field(default=None, max_length=160)
    params: dict | None = None
    consent: ConsentIn
    campaign_id: str | None = Field(default=None, max_length=64)
    utm: UTM | None = None
    channel: str | None = Field(default=None, max_length=64)
    source: str | None = Field(default=None, max_length=64)
    #: client-generated key; the server also derives its own business key
    idempotency_key: str | None = Field(default=None, max_length=64)

    @field_validator("customer_phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        if not _PHONE_RE.match(value.strip()):
            raise ValueError("teléfono con formato inválido")
        return value.strip()

    @field_validator("customer_name", "message")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class LeadDecision(BaseModel):
    """Partner-side CRM action (manual reconciliation is allowed — §07)."""

    status: LeadStatus
    note: str | None = Field(default=None, max_length=1000)
    rejection_reason_es: str | None = Field(default=None, max_length=300)
    requested_when: str | None = Field(default=None, max_length=160)

    @field_validator("status")
    @classmethod
    def _allowed(cls, value: LeadStatus) -> LeadStatus:
        allowed = {
            LeadStatus.ACCEPTED,
            LeadStatus.REJECTED,
            LeadStatus.BOOKED,
            LeadStatus.VISIT_DONE,
            LeadStatus.CANCELLED,
        }
        if value not in allowed:
            raise ValueError(
                "use el endpoint de venta confirmada para sale_confirmed; "
                f"estados permitidos aquí: {sorted(s.value for s in allowed)}"
            )
        return value


class SaleConfirm(BaseModel):
    """Confirmed commercial result with proof (§06, §10).

    ``amount_pyg`` is the seller's transaction amount (GMV) — PRTDS revenue is
    computed separately by the settlement engine and is never equal to it.
    """

    amount_pyg: int = Field(ge=0)
    proof_ref: str | None = Field(default=None, max_length=120)
    occurred_at: datetime | None = None
    note: str | None = Field(default=None, max_length=1000)
    is_repeat: bool = False
    idempotency_key: str | None = Field(default=None, max_length=64)

    @field_validator("amount_pyg")
    @classmethod
    def _no_fraction(cls, value: int) -> int:
        # PYG has no fractional units; the API refuses them explicitly.
        return int(value)


# --------------------------------------------------------------------------- #
# Contracts, rules, publication (§10, §13.2)
# --------------------------------------------------------------------------- #
class CommissionRuleIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    scope: str = Field(default="company", pattern=r"^(company|category|global)$")
    company_slug: str | None = None
    category_slug: str | None = None
    applies_to: str = Field(default="sale_confirmed", max_length=40)
    rate_percent: float | None = Field(default=None, ge=0, le=100)
    fixed_amount_pyg: int = Field(default=0, ge=0)
    min_amount_pyg: int = Field(default=0, ge=0)
    max_amount_per_event_pyg: int | None = Field(default=None, ge=0)
    priority: int = Field(default=100, ge=0, le=1000)
    is_active: bool = True
    notes: str | None = Field(default=None, max_length=1000)


class ContractIn(BaseModel):
    company_slug: str
    number: str = Field(min_length=2, max_length=64)
    counterparty_name: str = Field(min_length=2, max_length=300)
    contact_name: str | None = Field(default=None, max_length=200)
    status: ContractStatus = ContractStatus.ACTIVE
    billing_model: BillingModel
    rule_name: str | None = Field(default=None, max_length=200)
    signed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    attribution_window_days: int = Field(default=7, ge=0, le=90)
    cap_amount_pyg: int | None = Field(default=None, ge=0)
    cap_period: CapPeriod = CapPeriod.NONE
    postpaid: bool = True
    proof_requirements: dict | None = None
    direct_costs_pyg: int = Field(default=0, ge=0)
    notes: str | None = Field(default=None, max_length=1000)
    partner_users: list[dict] | None = None


class PublicationChange(BaseModel):
    """staging → validation → moderation → publication (§13.2)."""

    status: PublicationStatus
    reason: str | None = Field(default=None, max_length=300)
    allowed_transitions: dict[str, list[str]] | None = None


class SourceIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    kind: str = Field(default="manual", max_length=32)
    url: str | None = Field(default=None, max_length=500)
    retrieved_at: datetime | None = None
    license_note: str | None = Field(default=None, max_length=1000)
    trusted: bool = False
