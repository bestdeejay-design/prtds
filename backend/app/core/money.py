"""Money and rate arithmetic for PYG.

Rules taken from the concept document:

* §02 — PYG is displayed **without fractional units** (``G. 1.250.000``).
* §09 — effective price = seller price − applicable discounts − confirmed
  benefit components + delivery/pickup fee + applicable charges. A future bank
  cashback that depends on unknown personal limits is shown **separately** as
  potential, never folded into the guaranteed price.
* §10 — PRTDS revenue is its commission/service fee, **not** the GMV of the
  seller. 5% of a 100 000 G. basket is 5 000 G. of revenue, not 100 000 G.
* §10 — hard unit-economics rule: contribution margin of a completed commercial
  operation must be > 0; a negative margin is flagged, never silently approved.

Amounts are integers (guaraníes). Rates are basis points (10_000 bps = 100%).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

RATE_DENOMINATOR = 10_000  # basis points


def pct_to_bps(percent: float | str | Decimal) -> int:
    """``5`` or ``5.0`` percent -> ``500`` basis points."""
    value = Decimal(str(percent)) * Decimal(100)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def bps_to_pct(rate_bps: int) -> Decimal:
    return (Decimal(rate_bps) / Decimal(100)).quantize(Decimal("0.001"))


def apply_bps(amount: int, rate_bps: int) -> int:
    """Integer, half-up rounded share of ``amount`` for ``rate_bps``."""
    if not amount or not rate_bps:
        return 0
    value = Decimal(amount) * Decimal(rate_bps) / Decimal(RATE_DENOMINATOR)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_pyg(amount: int | None, *, with_symbol: bool = True) -> str:
    """``1250000`` -> ``G. 1.250.000`` (es-PY grouping, no decimals)."""
    if amount is None:
        return "—"
    negative = amount < 0
    digits = f"{abs(int(amount)):,}".replace(",", ".")
    text = f"G. {digits}" if with_symbol else digits
    return f"-{text}" if negative else text


@dataclass(slots=True)
class EffectivePrice:
    """Deterministic price breakdown (concept §09).

    ``potential_cashback`` is *not* part of ``effective_total``: it depends on
    bank rules and personal limits PRTDS may not know, so it is displayed
    separately and labelled conditional.
    """

    currency: str
    base_price: int
    seller_discount: int = 0
    confirmed_benefits: int = 0
    delivery_fee: int = 0
    pickup_fee: int = 0
    charges: int = 0
    potential_cashback: int = 0
    potential_cashback_conditional: bool = True
    rule_provenance: list[str] | None = None

    @property
    def effective_total(self) -> int:
        total = (
            self.base_price
            - self.seller_discount
            - self.confirmed_benefits
            + self.delivery_fee
            + self.pickup_fee
            + self.charges
        )
        return max(total, 0)

    def as_dict(self) -> dict:
        return {
            "currency": self.currency,
            "base_price": self.base_price,
            "base_price_display": format_pyg(self.base_price),
            "seller_discount": self.seller_discount,
            "confirmed_benefits": self.confirmed_benefits,
            "delivery_fee": self.delivery_fee,
            "pickup_fee": self.pickup_fee,
            "charges": self.charges,
            "effective_total": self.effective_total,
            "effective_total_display": format_pyg(self.effective_total),
            "potential_cashback": self.potential_cashback,
            "potential_cashback_display": format_pyg(self.potential_cashback),
            "potential_cashback_conditional": self.potential_cashback_conditional,
            "rule_provenance": self.rule_provenance or [],
        }


@dataclass(slots=True)
class ContributionMargin:
    """Per-operation economics (concept §10 hard rule)."""

    commission: int
    other_confirmed_funding: int = 0
    prtds_funded_discounts: int = 0
    direct_costs: int = 0  # AI, payments, support, delivery, partner payouts

    @property
    def total(self) -> int:
        return (
            self.commission
            + self.other_confirmed_funding
            - self.prtds_funded_discounts
            - self.direct_costs
        )

    @property
    def is_positive(self) -> bool:
        return self.total > 0
