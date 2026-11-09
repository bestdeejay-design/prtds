"""Text normalisation for search.

Spanish (and Guaraní) search must be accent-insensitive: a person types
"movil", "celular" or "asuncion" without diacritics on a phone keyboard.

Dev/pilot implementation: an accent-folded, lower-cased search blob is stored on
the company row (``search_text_norm``) and matched with ``LIKE``. It is portable
across SQLite and PostgreSQL and needs no extension.

Production path (documented in docs/architecture.md):
    * PostgreSQL ``unaccent`` + ``tsvector`` with the Spanish text search
      configuration and a GIN index for ranked full-text search;
    * ``pg_trgm`` for typos and partial words;
    * PostGIS ``geography`` + GiST index for "near me" queries.
The folded column stays useful as a deterministic fallback and for exports.
"""

from __future__ import annotations

import unicodedata

#: characters that must survive folding (ñ is meaningful in Spanish/Guaraní,
#: but for matching we fold it to n and keep the original string for display)
def fold(value: str | None) -> str:
    """Lower-case, strip diacritics, collapse whitespace."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(without_marks.lower().split())


def contains(haystack: str | None, needle: str | None) -> bool:
    return bool(needle) and fold(needle) in fold(haystack)
