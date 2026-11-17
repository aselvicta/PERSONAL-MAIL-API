from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.validators import HeaderSafeStr

NotificationType = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.\-]*$")
]
DetailKey = Annotated[str, StringConstraints(min_length=1, max_length=100)]
DetailValue = Annotated[str, StringConstraints(max_length=1000)] | int | float | bool | None


class NotificationRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "type": "user.registered",
                    "subject": "New user registration",
                    "message": "A new user just signed up.",
                    "details": {"Email": "jane@example.com", "Plan": "Pro"},
                }
            ]
        },
    )

    type: NotificationType = Field(description="e.g. user.registered, business.enquiry")
    subject: HeaderSafeStr = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=10_000)
    details: dict[DetailKey, DetailValue] = Field(default_factory=dict, max_length=25)
