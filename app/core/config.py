"""Centralised application configuration.

Every setting is read from environment variables (or a local ``.env`` file in
development). Nothing environment-specific is hardcoded.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import EmailStr, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

MIN_PRODUCTION_SECRET_LENGTH = 32


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
        # Treat `KEY=` in .env as "unset" so defaults apply.
        env_ignore_empty=True,
    )

    # --- Application -------------------------------------------------------
    APP_NAME: str = "Personal Mail API"
    APP_ENV: Environment = Environment.DEVELOPMENT
    APP_VERSION: str = "1.0.0"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    DOCS_ENABLED: bool = True
    # Built-in admin web page at /admin (login + project management).
    ADMIN_UI_ENABLED: bool = True

    # --- Database (Supabase PostgreSQL in production) -----------------------
    DATABASE_URL: SecretStr
    # libpq sslmode. Defaults to "require" in production when unset.
    DATABASE_SSL_MODE: (
        Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] | None
    ) = None
    # Supabase's transaction pooler (port 6543) does not support prepared
    # statements. Leave unset to auto-detect from the port.
    DATABASE_TRANSACTION_POOLER: bool | None = None
    DATABASE_POOL_SIZE: int = Field(default=5, ge=1, le=50)
    DATABASE_MAX_OVERFLOW: int = Field(default=5, ge=0, le=50)
    DATABASE_POOL_TIMEOUT_SECONDS: int = Field(default=30, ge=1)
    DATABASE_POOL_RECYCLE_SECONDS: int = Field(default=1800, ge=60)

    # --- Resend ------------------------------------------------------------
    RESEND_API_KEY: SecretStr | None = None
    RESEND_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0, le=60)
    RESEND_WEBHOOK_SECRET: SecretStr | None = None
    DEFAULT_FROM_EMAIL: EmailStr | None = None
    DEFAULT_FROM_NAME: str = "Personal Mail API"

    # --- Administrator authentication ---------------------------------------
    JWT_SECRET_KEY: SecretStr
    JWT_ALGORITHM: Literal["HS256", "HS384", "HS512"] = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, ge=1, le=1440)
    # Optional bootstrap administrator, applied at container start by
    # scripts/bootstrap_admin.py (for hosts without a shell, e.g. Render free).
    # The environment is the source of truth: changing ADMIN_PASSWORD and
    # redeploying updates the password.
    ADMIN_EMAIL: EmailStr | None = None
    ADMIN_PASSWORD: SecretStr | None = None

    # Domains projects may send from. Empty means only the DEFAULT_FROM_EMAIL
    # domain. Every domain listed must be verified in Resend.
    ALLOWED_SENDER_DOMAINS: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- HTTP / abuse protection --------------------------------------------
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(default_factory=list)
    TURNSTILE_SECRET_KEY: SecretStr | None = None
    RATE_LIMIT_ENABLED: bool = True
    # Contact form submissions allowed per client IP, per project, per hour.
    CONTACT_RATE_LIMIT_PER_IP: int = Field(default=5, ge=1)
    # Admin login attempts allowed per client IP per 15 minutes.
    LOGIN_RATE_LIMIT_PER_IP: int = Field(default=10, ge=1)
    MAX_REQUEST_BODY_BYTES: int = Field(default=512 * 1024, ge=1024)
    # Number of reverse proxies in front of the app that append to
    # X-Forwarded-For (Render: 1). 0 means use the socket peer address.
    TRUSTED_PROXY_COUNT: int = Field(default=0, ge=0, le=5)
    # Maximum accepted age of a webhook signature timestamp.
    WEBHOOK_TOLERANCE_SECONDS: int = Field(default=300, ge=30)

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [o.strip().rstrip("/") for o in value.split(",") if o.strip()]
        return value

    @field_validator("ALLOWED_SENDER_DOMAINS", mode="before")
    @classmethod
    def _split_domains(cls, value: object) -> object:
        if isinstance(value, str):
            return [d.strip().lower() for d in value.split(",") if d.strip()]
        return value

    @property
    def sender_domains(self) -> set[str]:
        """Domains a project's sender_email may use. Empty means unrestricted."""
        domains = set(self.ALLOWED_SENDER_DOMAINS)
        if not domains and self.DEFAULT_FROM_EMAIL:
            domains.add(self.DEFAULT_FROM_EMAIL.rsplit("@", 1)[1].lower())
        return domains

    @field_validator("DEFAULT_FROM_NAME")
    @classmethod
    def _no_header_injection(cls, value: str) -> str:
        if "\r" in value or "\n" in value:
            raise ValueError("must not contain line breaks")
        return value.strip()

    @model_validator(mode="after")
    def _production_requirements(self) -> Settings:
        if self.APP_ENV is not Environment.PRODUCTION:
            return self
        problems: list[str] = []
        if len(self.JWT_SECRET_KEY.get_secret_value()) < MIN_PRODUCTION_SECRET_LENGTH:
            problems.append(
                f"JWT_SECRET_KEY must be at least {MIN_PRODUCTION_SECRET_LENGTH} characters"
            )
        if not self.RESEND_API_KEY:
            problems.append("RESEND_API_KEY is required")
        if not self.DEFAULT_FROM_EMAIL:
            problems.append("DEFAULT_FROM_EMAIL is required")
        if "*" in self.CORS_ORIGINS:
            problems.append("CORS_ORIGINS must not contain '*' in production")
        if problems:
            raise ValueError("Invalid production configuration: " + "; ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.APP_ENV is Environment.PRODUCTION

    @property
    def effective_ssl_mode(self) -> str | None:
        if self.DATABASE_SSL_MODE:
            return self.DATABASE_SSL_MODE
        return "require" if self.is_production else None


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
