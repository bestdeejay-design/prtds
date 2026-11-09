"""Database engine, session management and declarative base.

Design notes
------------
* The system of record for commercial facts is PostgreSQL (concept §13.1). Local
  development in the sandbox uses SQLite because no PostgreSQL server is
  available there; the schema is written so that the move is mechanical
  (Alembic migrations, no dialect-specific column types, no stored procedures).
* Money is stored as **integer guaraníes** (PYG has no fractional units) and
  rates as **basis points** — this keeps arithmetic exact on every dialect and
  matches the "effective price" rules of concept §09.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base for every PRTDS table."""


def _ensure_sqlite_dir(url: str) -> None:
    if not url.startswith("sqlite"):
        return
    path = url.split("///", 1)[-1]
    if path and path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)


def build_engine(database_url: str | None = None, echo: bool | None = None) -> Engine:
    url = database_url or settings.database_url
    _ensure_sqlite_dir(url)

    if url.startswith("sqlite"):
        engine = create_engine(
            url,
            echo=bool(settings.echo_sql if echo is None else echo),
            connect_args={"check_same_thread": False},
            future=True,
        )

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        return engine

    # PostgreSQL (Neon) — production path.
    return create_engine(
        url,
        echo=bool(settings.echo_sql if echo is None else echo),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        future=True,
    )


engine: Engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_all_for_tests(database_url: str = "sqlite:///:memory:") -> tuple[Engine, sessionmaker]:
    """Create an isolated engine + session factory (used by the test suite)."""
    test_engine = build_engine(database_url)
    # Importing models registers every table on Base.metadata.
    from app.domain import models  # noqa: F401

    Base.metadata.create_all(test_engine)
    factory = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False, future=True)
    return test_engine, factory


DATA_DIR = Path(os.environ.get("PRTDS_DATA_DIR", "data"))
