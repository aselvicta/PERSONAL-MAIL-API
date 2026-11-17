from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.validators import Email, HeaderSafeStr, Slug


class ContactRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "project": "portfolio",
                    "name": "John Doe",
                    "email": "john@example.com",
                    "subject": "Software Development Opportunity",
                    "message": "I would like to discuss a project with you.",
                }
            ]
        },
    )

    project: Slug = Field(description="Public project identifier (slug)")
    name: HeaderSafeStr = Field(min_length=1, max_length=100)
    email: Email
    subject: HeaderSafeStr = Field(
        default="New contact form submission", min_length=1, max_length=200
    )
    message: str = Field(min_length=1, max_length=5000)
    turnstile_token: str | None = Field(
        default=None, max_length=4096, description="Cloudflare Turnstile response token"
    )
    # Honeypot: hide this input from humans with CSS. Bots that fill it are
    # silently ignored.
    website: str | None = Field(default=None, max_length=500)


class ContactAccepted(BaseModel):
    id: uuid.UUID
    status: str


class ContactSubmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    sender_name: str
    sender_email: str
    subject: str
    message: str
    status: str
    resend_message_id: str | None
    created_at: datetime
