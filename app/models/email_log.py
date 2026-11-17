from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import EMAIL_PROVIDER_RESEND, EmailStatus


class EmailLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "email_logs"
    __table_args__ = (Index("ix_email_logs_project_id_created_at", "project_id", "created_at"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(32), default=EMAIL_PROVIDER_RESEND, server_default=EMAIL_PROVIDER_RESEND
    )
    # Webhooks locate the log by this value.
    resend_message_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default=EmailStatus.PENDING,
        server_default=EmailStatus.PENDING.value,
        index=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
