"""Alembic environment.

The connection comes from the application's settings (``DATABASE_URL``), with
the same SSL and pooler handling as the running app. A caller (such as the
test suite) can pass an existing connection through
``config.attributes["connection"]``.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, create_engine, pool, text

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.core.config import get_settings
from app.database.base import Base
from app.database.session import engine_options

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# Serialises concurrent `alembic upgrade` runs (e.g. several instances booting
# at once). Transaction-scoped, so it is released automatically on commit.
MIGRATION_LOCK_ID = 7_340_118_001


def _run_locked(connection: Connection) -> None:
    with context.begin_transaction():
        connection.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": MIGRATION_LOCK_ID})
        context.run_migrations()


def _configure(connection: Connection | None = None, **kwargs: object) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        **kwargs,  # type: ignore[arg-type]
    )


def run_migrations_offline() -> None:
    url, _ = engine_options(get_settings())
    _configure(url=url.render_as_string(hide_password=False), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    existing: Connection | None = config.attributes.get("connection")
    if existing is not None:
        _configure(connection=existing)
        _run_locked(existing)
        return

    url, options = engine_options(get_settings())
    # A single short-lived connection: migrations must not use the app's pool.
    engine = create_engine(url, poolclass=pool.NullPool, connect_args=options["connect_args"])
    with engine.connect() as connection:
        _configure(connection=connection)
        _run_locked(connection)
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
