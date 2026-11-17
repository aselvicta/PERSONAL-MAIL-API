from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ContactStatus


class ContactSubmission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "contact_submissions"
    __table_args__ = (
        Index("ix_contact_submissions_project_id_created_at", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    sender_name: Mapped[str] = mapped_column(String(100), nullable=False)
    sender_email: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=ContactStatus.RECEIVED, server_default=ContactStatus.RECEIVED.value
    )
    resend_message_id: Mapped[str | None] = mapped_column(String(100))
