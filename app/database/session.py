"""Database engine and session management.

The engine is created lazily, so importing the application never opens a
connection. It is configured for Supabase PostgreSQL behind Render:

* ``postgres://`` and ``postgresql://`` URLs are normalised to the psycopg 3 driver.
* SSL is required in production (override with ``DATABASE_SSL_MODE``).
* Supabase's transaction pooler (port 6543) cannot use prepared statements,
  so they are disabled when that pooler is detected.
* ``pool_pre_ping`` and ``pool_recycle`` survive idle connections being
  dropped by the pooler or the platform.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings

SUPABASE_TRANSACTION_POOLER_PORT = 6543


def normalize_database_url(raw_url: str) -> URL:
    url = make_url(raw_url)
    if url.drivername in {"postgres", "postgresql", "postgresql+psycopg2"}:
        url = url.set(drivername="postgresql+psycopg")
    if url.drivername != "postgresql+psycopg":
        raise ValueError("DATABASE_URL must be a PostgreSQL connection string")
    return url


def engine_options(settings: Settings) -> tuple[URL, dict[str, Any]]:
    url = normalize_database_url(settings.DATABASE_URL.get_secret_value())

    connect_args: dict[str, Any] = {"connect_timeout": 10}
    ssl_mode = settings.effective_ssl_mode
    if ssl_mode and "sslmode" not in url.query:
        connect_args["sslmode"] = ssl_mode

    transaction_pooler = settings.DATABASE_TRANSACTION_POOLER
    if transaction_pooler is None:
        transaction_pooler = url.port == SUPABASE_TRANSACTION_POOLER_PORT
    if transaction_pooler:
        connect_args["prepare_threshold"] = None

    options: dict[str, Any] = {
        "pool_pre_ping": True,
        "pool_size": settings.DATABASE_POOL_SIZE,
        "max_overflow": settings.DATABASE_MAX_OVERFLOW,
        "pool_timeout": settings.DATABASE_POOL_TIMEOUT_SECONDS,
        "pool_recycle": settings.DATABASE_POOL_RECYCLE_SECONDS,
        "connect_args": connect_args,
    }
    return url, options


def build_engine(settings: Settings) -> Engine:
    url, options = engine_options(settings)
    return create_engine(url, **options)


@lru_cache
def get_engine() -> Engine:
    return build_engine(get_settings())


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a session and always closes it."""
    session = get_sessionmaker()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
