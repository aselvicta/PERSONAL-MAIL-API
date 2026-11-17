from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class EmailEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "email_events"

    # NULL when a verified webhook references an email this service has no log for.
    email_log_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("email_logs.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # The Svix message id. The unique constraint makes webhook handling idempotent.
    provider_event_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    event_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
