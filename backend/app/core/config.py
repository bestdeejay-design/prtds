"""Application settings.

All values can be overridden by environment variables with the ``PRTDS_`` prefix
(e.g. ``PRTDS_DATABASE_URL``). No credentials are ever stored in the repository —
see docs/architecture.md, section "Secrets".
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PRTDS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- runtime -----------------------------------------------------------
    app_env: str = "development"
    host: str = "0.0.0.0"  # must stay 0.0.0.0: the preview proxy reaches us there
    port: int = 8000
    public_site_url: str = "http://localhost:8000"

    # --- data --------------------------------------------------------------
    # Dev: SQLite file. Prod: postgresql+psycopg://... (Neon) — set via env.
    database_url: str = "sqlite:///./data/prtds_dev.db"
    echo_sql: bool = False

    # --- locale / market ---------------------------------------------------
    default_locale: str = "es-PY"
    default_currency: str = "PYG"  # no fractional units for PYG
    timezone_name: str = "America/Asuncion"
    default_country: str = "PY"

    # --- funnel / attribution ---------------------------------------------
    attribution_window_days: int = 7
    max_events_per_request: int = 100

    # --- dev-only cabinet auth ---------------------------------------------
    # Shared demo tokens exist so the team can verify the funnel locally.
    # Production must use real identity (Google Identity Services per concept
    # §12) with role separation — never these values, and never in documents.
    demo_partner_token: str = "prtds-demo-partner-token"
    demo_admin_token: str = "prtds-demo-admin-token"

    # --- commerce defaults (§10) -------------------------------------------
    #: illustrative negotiation range, NOT a platform tariff
    default_rate_bps: int = 500
    #: standard variable cost per confirmed operation (AI, payments, support)
    default_direct_costs_pyg: int = 0

    cors_allow_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
