"""Shared test fixtures.

Tests run against a real, isolated PostgreSQL database (``TEST_DATABASE_URL``,
default: the ``personal_mail_test`` database of ``docker compose up -d db``).
The schema is rebuilt from the Alembic migrations once per session, and every
test runs inside a transaction that is rolled back afterwards.

Resend is always replaced by an in-memory fake, so no real emails are sent.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/personal_mail_test"
)

# Configure the environment before any application module is imported.
os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": TEST_DATABASE_URL,
        "JWT_SECRET_KEY": "test-jwt-secret-key-with-enough-length-0123456789",
        "RESEND_API_KEY": "re_test_placeholder_not_a_real_key",
        "DEFAULT_FROM_EMAIL": "noreply@mail.example.com",
        "DEFAULT_FROM_NAME": "Personal Mail API",
        "LOG_LEVEL": "WARNING",
        "RESEND_WEBHOOK_SECRET": "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSwdGVzdC1zZWNyZXQ=",
        "TURNSTILE_SECRET_KEY": "",
        "RATE_LIMIT_ENABLED": "true",
        "TRUSTED_PROXY_COUNT": "0",
        "ALLOWED_SENDER_DOMAINS": "",
        "CORS_ORIGINS": "",
    }
)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import Settings, get_settings  # noqa: E402

# Never let a developer's local .env leak into the test run.
Settings.model_config["env_file"] = None
get_settings.cache_clear()

from app.core.security import create_access_token  # noqa: E402
from app.database.session import build_engine, get_db, normalize_database_url  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Administrator, Project  # noqa: E402
from app.schemas.project import ProjectCreate  # noqa: E402
from app.services.auth_service import create_admin  # noqa: E402
from app.services.project_service import ProjectService  # noqa: E402
from app.services.resend_service import (  # noqa: E402
    OutboundEmail,
    SendResult,
    SendStatus,
    get_resend_service,
)
from app.services.turnstile_service import get_turnstile_verifier  # noqa: E402

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "correct-horse-battery-staple"

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def alembic_config() -> Config:
    cfg = Config(os.path.join(PROJECT_ROOT, "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def engine(settings: Settings) -> Iterator[Engine]:
    database = normalize_database_url(TEST_DATABASE_URL).database or ""
    if not database.endswith("_test"):
        pytest.exit(
            f"Refusing to run: test database name {database!r} must end with '_test' "
            "because the test suite drops its schema.",
            returncode=2,
        )
    eng = build_engine(settings)
    try:
        with eng.begin() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    except Exception as exc:
        pytest.exit(
            f"Cannot connect to the test database. Start it with `docker compose up -d db` "
            f"or set TEST_DATABASE_URL. ({type(exc).__name__})",
            returncode=2,
        )
    command.upgrade(alembic_config(), "head")
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """A session whose commits are released savepoints. Everything is rolled back."""
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


@dataclass
class FakeResendService:
    """In-memory replacement for ResendService. Records every email."""

    result: SendResult = field(
        default_factory=lambda: SendResult(status=SendStatus.ACCEPTED, message_id="msg_fake_1")
    )
    sent: list[OutboundEmail] = field(default_factory=list)
    configured: bool = True

    def send(self, email: OutboundEmail) -> SendResult:
        self.sent.append(email)
        if self.result.accepted:
            # Real Resend message ids are unique: msg_fake_1, msg_fake_2, ...
            return SendResult(status=SendStatus.ACCEPTED, message_id=f"msg_fake_{len(self.sent)}")
        return self.result


@pytest.fixture
def fake_resend() -> FakeResendService:
    return FakeResendService()


@dataclass
class FakeTurnstile:
    configured: bool = True
    valid_token: str = "valid-token"
    calls: list[tuple[str, str | None]] = field(default_factory=list)

    def verify(self, token: str, remote_ip: str | None = None) -> bool:
        self.calls.append((token, remote_ip))
        return token == self.valid_token


@pytest.fixture
def fake_turnstile() -> FakeTurnstile:
    return FakeTurnstile()


@pytest.fixture
def app(
    db_session: Session, fake_resend: FakeResendService, fake_turnstile: FakeTurnstile
) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_db] = lambda: db_session
    application.dependency_overrides[get_resend_service] = lambda: fake_resend
    application.dependency_overrides[get_turnstile_verifier] = lambda: fake_turnstile
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def project(db_session: Session) -> Project:
    proj = Project(
        name="Portfolio",
        slug="portfolio",
        recipient_email="owner@example.com",
        sender_name="Portfolio",
        sender_email="portfolio@mail.example.com",
        allowed_origins=["https://portfolio.example.com"],
    )
    db_session.add(proj)
    db_session.commit()
    return proj


@pytest.fixture
def admin(db_session: Session) -> Administrator:
    return create_admin(db_session, ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture
def admin_headers(admin: Administrator, settings: Settings) -> dict[str, str]:
    token = create_access_token(admin.id, settings)
    return {"Authorization": f"Bearer {token.token}"}


@dataclass
class KeyedProject:
    project: Project
    api_key: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}


def make_project(db: Session, settings: Settings, **overrides: object) -> KeyedProject:
    values: dict[str, object] = {
        "name": "CareerDocs",
        "slug": "careerdocs",
        "recipient_email": "owner@example.com",
        "transactional_enabled": True,
    }
    values.update(overrides)
    project, issued = ProjectService(db, settings).create(ProjectCreate(**values))  # type: ignore[arg-type]
    return KeyedProject(project=project, api_key=issued.plaintext)


@pytest.fixture
def keyed_project(db_session: Session, settings: Settings) -> KeyedProject:
    return make_project(db_session, settings)


@pytest.fixture
def other_project(db_session: Session, settings: Settings) -> KeyedProject:
    return make_project(
        db_session,
        settings,
        name="Safari AI",
        slug="safari-ai",
        recipient_email="safari@example.com",
    )
