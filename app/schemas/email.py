from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.validators import Email, HeaderSafeStr

MAX_HTML_BYTES = 200_000
MAX_TEXT_BYTES = 100_000

TransactionalTemplate = Literal["welcome", "password_reset", "email_verification", "notification"]
VariableKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,49}$")]
VariableValue = str | int | float | bool | None


class SendEmailRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "to": "user@example.com",
                    "subject": "Welcome to CareerDocs",
                    "html": "<h1>Welcome!</h1>",
                    "text": "Welcome to CareerDocs.",
                    "reply_to": "support@example.com",
                },
                {
                    "to": "user@example.com",
                    "template": "password_reset",
                    "variables": {
                        "app_name": "CareerDocs",
                        "name": "Jane",
                        "reset_url": "https://careerdocs.example.com/reset?token=abc",
                    },
                },
            ]
        },
    )

    to: Email
    subject: HeaderSafeStr | None = Field(default=None, min_length=1, max_length=200)
    html: str | None = Field(default=None, max_length=MAX_HTML_BYTES)
    text: str | None = Field(default=None, max_length=MAX_TEXT_BYTES)
    reply_to: Email | None = None
    sender_name: HeaderSafeStr | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Display name only. The sender address is always the project's verified one.",
    )
    template: TransactionalTemplate | None = None
    variables: dict[VariableKey, VariableValue] = Field(default_factory=dict, max_length=30)

    @model_validator(mode="after")
    def _content_source(self) -> Self:
        if self.template:
            if self.html or self.text:
                raise ValueError("use either 'template' or 'html'/'text', not both")
        else:
            if self.variables:
                raise ValueError("'variables' requires 'template'")
            if not self.subject:
                raise ValueError("'subject' is required when no template is used")
            if not (self.html or self.text):
                raise ValueError("'html' or 'text' is required when no template is used")
        return self


class EmailAccepted(BaseModel):
    id: uuid.UUID = Field(description="Email log id")
    message_id: str | None = Field(description="Resend message id")
    status: str


class EmailEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_type: str
    created_at: datetime


class EmailLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    recipient: str
    subject: str
    email_type: str
    provider: str
    resend_message_id: str | None
    status: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class EmailLogDetail(EmailLogRead):
    events: list[EmailEventRead]
