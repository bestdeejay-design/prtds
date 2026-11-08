"""Token helpers for the dev cabinets.

Concept §13.4: secrets live only in a protected environment and never in
documents. These helpers store a SHA-256 hash so that a leaked database row
cannot be replayed as a bearer token. Production must replace this with real
identity (Google Identity Services) plus role separation.
"""

from __future__ import annotations

import hashlib
import hmac


def hash_token(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def token_matches(raw: str | None, token_hash: str) -> bool:
    if not raw:
        return False
    return hmac.compare_digest(hash_token(raw), token_hash)
