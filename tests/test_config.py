from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.database.session import engine_options, normalize_database_url

BASE: dict[str, Any] = {
    "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
    "JWT_SECRET_KEY": "x" * 40,
}
PRODUCTION: dict[str, Any] = {
    **BASE,
    "APP_ENV": "production",
    "RESEND_API_KEY": "re_123456789",
    "DEFAULT_FROM_EMAIL": "noreply@example.com",
}


def make(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[call-arg]


def test_cors_origins_are_parsed_from_comma_separated_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example.com/, https://b.example.com")
    settings = make()
    assert settings.CORS_ORIGINS == ["https://a.example.com", "https://b.example.com"]


def test_empty_environment_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_SSL_MODE", "")
    monkeypatch.setenv("DATABASE_TRANSACTION_POOLER", "")
    settings = make()
    assert settings.DATABASE_SSL_MODE is None
    assert settings.DATABASE_TRANSACTION_POOLER is None


def test_production_accepts_complete_configuration() -> None:
    settings = make(**PRODUCTION)
    assert settings.is_production
    assert settings.effective_ssl_mode == "require"


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"JWT_SECRET_KEY": "too-short"}, "JWT_SECRET_KEY"),
        ({"RESEND_API_KEY": None}, "RESEND_API_KEY"),
        ({"DEFAULT_FROM_EMAIL": None}, "DEFAULT_FROM_EMAIL"),
        ({"CORS_ORIGINS": ["*"]}, "CORS_ORIGINS"),
    ],
)
def test_production_rejects_insecure_configuration(overrides: dict[str, Any], problem: str) -> None:
    with pytest.raises(ValidationError, match=problem):
        make(**{**PRODUCTION, **overrides})


def test_default_from_name_rejects_header_injection() -> None:
    with pytest.raises(ValidationError):
        make(DEFAULT_FROM_NAME="Evil\r\nBcc: victim@example.com")


def test_secrets_are_not_revealed_by_repr() -> None:
    settings = make(**PRODUCTION)
    assert "x" * 40 not in repr(settings)
    assert "re_123456789" not in repr(settings)


@pytest.mark.parametrize(
    "raw",
    [
        "postgres://u:p@host:5432/db",
        "postgresql://u:p@host:5432/db",
        "postgresql+psycopg2://u:p@host:5432/db",
        "postgresql+psycopg://u:p@host:5432/db",
    ],
)
def test_database_url_is_normalised_to_psycopg3(raw: str) -> None:
    assert normalize_database_url(raw).drivername == "postgresql+psycopg"


def test_non_postgres_database_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        normalize_database_url("sqlite:///local.db")


def test_supabase_transaction_pooler_disables_prepared_statements() -> None:
    settings = make(DATABASE_URL="postgresql://u:p@aws-0-eu.pooler.supabase.com:6543/postgres")
    _, options = engine_options(settings)
    assert options["connect_args"]["prepare_threshold"] is None


def test_session_pooler_keeps_prepared_statements() -> None:
    settings = make(DATABASE_URL="postgresql://u:p@aws-0-eu.pooler.supabase.com:5432/postgres")
    _, options = engine_options(settings)
    assert "prepare_threshold" not in options["connect_args"]
    assert options["pool_pre_ping"] is True


def test_production_requires_ssl_by_default() -> None:
    _, options = engine_options(make(**PRODUCTION))
    assert options["connect_args"]["sslmode"] == "require"


def test_sslmode_in_url_takes_precedence() -> None:
    settings = make(
        **{**PRODUCTION, "DATABASE_URL": "postgresql://u:p@h:5432/db?sslmode=verify-full"}
    )
    url, options = engine_options(settings)
    assert url.query["sslmode"] == "verify-full"
    assert "sslmode" not in options["connect_args"]
