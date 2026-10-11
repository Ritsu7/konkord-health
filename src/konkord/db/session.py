"""Database engine/session wiring.

Connection target is controlled by the `KONKORD_DATABASE_URL` environment
variable. Defaults to a local SQLite file for development/tests; production
deployments should set it to a PostgreSQL URL, e.g.:

    postgresql+psycopg://konkord:konkord@localhost:5432/konkord
"""
from __future__ import annotations
import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

DEFAULT_DATABASE_URL = "sqlite:///./konkord.db"


def _database_url() -> str:
    return os.environ.get("KONKORD_DATABASE_URL", DEFAULT_DATABASE_URL)


def _make_engine():
    url = _database_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """Create tables if they do not already exist.

    Convenient for local development and tests (no migration step needed).
    Production and any schema-evolution-sensitive deployment should instead
    run `alembic upgrade head` (see `alembic/`) against `KONKORD_DATABASE_URL`
    before starting the API; `init_db()`'s `create_all` is a no-op once the
    tables already exist, so running both is safe but migrations should be
    the source of truth for schema changes going forward.
    """
    Base.metadata.create_all(bind=engine)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a request-scoped Session, closed after use."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
