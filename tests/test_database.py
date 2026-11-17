"""Database connectivity, migration integrity and schema constraints."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.base import Base
from app.models import ApiKey, EmailEvent, EmailLog, EmailType, Project
from tests.conftest import alembic_config


def test_database_connectivity(db_session: Session) -> None:
    assert db_session.execute(text("SELECT 1")).scalar_one() == 1


def test_migrations_match_models(engine: Engine) -> None:
    """Fails if a model changed without a matching Alembic migration."""
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": True}
        )
        diff = compare_metadata(context, Base.metadata)
    assert diff == []


def test_migrations_downgrade_and_upgrade_cleanly(engine: Engine) -> None:
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    command.upgrade(cfg, "head")
    assert {"projects", "api_keys", "email_logs", "email_events"} <= set(
        inspect(engine).get_table_names()
    )


def test_project_slug_is_unique(db_session: Session, project: Project) -> None:
    db_session.add(Project(name="Dup", slug=project.slug, recipient_email="a@example.com"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_project_secure_defaults(db_session: Session) -> None:
    proj = Project(name="New", slug="new", recipient_email="a@example.com")
    db_session.add(proj)
    db_session.flush()
    db_session.refresh(proj)
    assert proj.transactional_enabled is False
    assert proj.acknowledgement_enabled is False
    assert proj.is_active is True
    assert proj.allowed_origins == []
    assert proj.rate_limit > 0 and proj.daily_quota > 0


def test_rate_limit_must_be_positive(db_session: Session) -> None:
    db_session.add(Project(name="Bad", slug="bad", recipient_email="a@example.com", rate_limit=0))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_deleting_project_cascades(db_session: Session, project: Project) -> None:
    db_session.add(ApiKey(project_id=project.id, key_prefix="pmk_abcd", key_hash="0" * 64))
    log = EmailLog(
        project_id=project.id,
        recipient="u@example.com",
        subject="s",
        email_type=EmailType.TRANSACTIONAL.value,
    )
    db_session.add(log)
    db_session.flush()
    db_session.add(
        EmailEvent(
            email_log_id=log.id,
            event_type="email.sent",
            provider_event_id="msg_1",
            event_payload={},
        )
    )
    db_session.flush()

    db_session.execute(text("DELETE FROM projects WHERE id = :id"), {"id": project.id})

    for table in ("api_keys", "email_logs", "email_events"):
        assert db_session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0  # noqa: S608


def test_webhook_event_ids_are_unique(db_session: Session) -> None:
    db_session.add(EmailEvent(event_type="email.sent", provider_event_id="evt_1", event_payload={}))
    db_session.flush()
    db_session.add(EmailEvent(event_type="email.sent", provider_event_id="evt_1", event_payload={}))
    with pytest.raises(IntegrityError):
        db_session.flush()
