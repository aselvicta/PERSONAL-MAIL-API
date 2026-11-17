from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.validators import DomainList, Email, HeaderSafeStr, OriginList, Slug


class ProjectBase(BaseModel):
    description: str | None = Field(default=None, max_length=1000)
    sender_name: HeaderSafeStr | None = Field(default=None, min_length=1, max_length=100)
    sender_email: Email | None = None
    allowed_origins: OriginList = Field(default_factory=list, max_length=20)
    allowed_recipient_domains: DomainList = Field(default_factory=list, max_length=50)
    contact_enabled: bool = True
    transactional_enabled: bool = False
    notifications_enabled: bool = True
    acknowledgement_enabled: bool = False
    turnstile_enabled: bool = False
    rate_limit: int = Field(default=60, ge=1, le=10_000, description="Requests per minute")
    daily_quota: int = Field(default=500, ge=1, le=1_000_000, description="Emails per UTC day")


class ProjectCreate(ProjectBase):
    name: HeaderSafeStr = Field(min_length=1, max_length=100)
    slug: Slug
    recipient_email: Email


class ProjectUpdate(BaseModel):
    """Partial update. Only fields present in the request are changed."""

    name: HeaderSafeStr | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    recipient_email: Email | None = None
    sender_name: HeaderSafeStr | None = Field(default=None, min_length=1, max_length=100)
    sender_email: Email | None = None
    allowed_origins: OriginList | None = Field(default=None, max_length=20)
    allowed_recipient_domains: DomainList | None = Field(default=None, max_length=50)
    contact_enabled: bool | None = None
    transactional_enabled: bool | None = None
    notifications_enabled: bool | None = None
    acknowledgement_enabled: bool | None = None
    turnstile_enabled: bool | None = None
    rate_limit: int | None = Field(default=None, ge=1, le=10_000)
    daily_quota: int | None = Field(default=None, ge=1, le=1_000_000)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    recipient_email: str
    sender_name: str | None
    sender_email: str | None
    allowed_origins: list[str]
    allowed_recipient_domains: list[str]
    contact_enabled: bool
    transactional_enabled: bool
    notifications_enabled: bool
    acknowledgement_enabled: bool
    turnstile_enabled: bool
    is_active: bool
    rate_limit: int
    daily_quota: int
    created_at: datetime
    updated_at: datetime


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key_prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyRead):
    api_key: str = Field(description="The full key. Shown only once; store it securely.")


class ProjectCreated(BaseModel):
    project: ProjectRead
    api_key: ApiKeyCreated


class ProjectUsage(BaseModel):
    project_id: uuid.UUID
    emails_total: int
    emails_today: int
    daily_quota: int
    daily_quota_remaining: int
    emails_by_status: dict[str, int]
    emails_by_type: dict[str, int]
    contact_submissions_total: int
    api_key_last_used_at: datetime | None
