from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.api_key import ApiKey


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("rate_limit > 0", name="rate_limit_positive"),
        CheckConstraint("daily_quota > 0", name="daily_quota_positive"),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Public identifier. Contact forms send this; it is not a secret.
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Configured by the administrator only. The public can never choose it.
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    # Sender identity. Must be on a Resend-verified domain. NULL falls back to
    # DEFAULT_FROM_NAME / DEFAULT_FROM_EMAIL.
    sender_name: Mapped[str | None] = mapped_column(String(100))
    sender_email: Mapped[str | None] = mapped_column(String(320))

    allowed_origins: Mapped[list[str]] = mapped_column(
        ARRAY(String(255)), default=list, server_default=text("'{}'"), nullable=False
    )
    # Empty means transactional email may go to any domain.
    allowed_recipient_domains: Mapped[list[str]] = mapped_column(
        ARRAY(String(255)), default=list, server_default=text("'{}'"), nullable=False
    )

    contact_enabled: Mapped[bool] = mapped_column(default=True, server_default="true")
    # Off by default: sending to arbitrary recipients must be enabled explicitly.
    transactional_enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    notifications_enabled: Mapped[bool] = mapped_column(default=True, server_default="true")
    acknowledgement_enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    turnstile_enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")

    # Requests per minute across the whole project.
    rate_limit: Mapped[int] = mapped_column(default=60, server_default="60")
    # Maximum emails sent per UTC day.
    daily_quota: Mapped[int] = mapped_column(default=500, server_default="500")

    api_keys: Mapped[list[ApiKey]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
