"""Identifier helpers.

Every commercial object gets a prefixed, roughly time-sortable identifier so
that logs, support tickets and partner reports can be read by a human:

    cmp_1931f0a2c4b8d8e1   company
    br_...                 branch
    off_...                offer
    ld_...                 lead  (+ human ref_code PRTDS-2026-000123)
    ev_...                 funnel event
    ctr_...                contract
    stl_...                settlement
"""

from __future__ import annotations

import hashlib
import secrets
import time
from datetime import datetime, timezone

PREFIXES = {
    "source": "src",
    "legal_entity": "le",
    "brand": "brd",
    "category": "cat",
    "company": "cmp",
    "branch": "br",
    "contact": "ct",
    "offer": "off",
    "consent": "cns",
    "lead": "ld",
    "event": "ev",
    "attribution": "att",
    "contract": "ctr",
    "rule": "rule",
    "settlement": "stl",
    "partner_user": "pu",
}


def utcnow() -> datetime:
    """Timezone-aware UTC now (stored as ``TIMESTAMP WITH TIME ZONE`` in prod)."""
    return datetime.now(timezone.utc)


def new_id(kind: str) -> str:
    """Prefixed, time-sortable, unguessable identifier."""
    prefix = PREFIXES.get(kind, kind[:3])
    ts = format(int(time.time() * 1000), "011x")[-11:]
    return f"{prefix}_{ts}{secrets.token_hex(5)}"


def ref_code(seq: int, when: datetime | None = None) -> str:
    """Human reference for a lead, e.g. ``PRTDS-2026-000123``."""
    when = when or utcnow()
    return f"PRTDS-{when.year}-{seq:06d}"


def stable_hash(*parts: object) -> str:
    """SHA-256 (truncated) over business coordinates.

    Used for idempotency keys and event de-duplication. Deliberately built from
    server-side facts (event type + object ids + campaign + day bucket), never
    from free client input alone.
    """
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def hash_pii(value: str) -> str:
    """One-way hash for personal data we must be able to match but not store."""
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()
