from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings, get_settings
from app.core.exceptions import ConfigurationError
from app.database.session import get_db
from app.schemas.common import ERROR_RESPONSES, SuccessResponse, ok
from app.services.webhook_service import process_event, verify_signature

router = APIRouter(prefix="/webhooks", tags=["webhooks"], responses=ERROR_RESPONSES)


class WebhookResult(BaseModel):
    event_type: str
    duplicate: bool
    matched_email: bool
    status_changed: bool


@router.post("/resend", response_model=SuccessResponse[WebhookResult])
async def resend_webhook(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SuccessResponse[WebhookResult]:
    """Receive Resend delivery events. The Svix signature is always verified."""
    if not settings.RESEND_WEBHOOK_SECRET:
        raise ConfigurationError(
            "RESEND_WEBHOOK_SECRET is not configured.", code="WEBHOOK_NOT_CONFIGURED"
        )
    # The signature covers the exact raw bytes, so read the body unparsed.
    body = await request.body()
    verify_signature(
        secret=settings.RESEND_WEBHOOK_SECRET.get_secret_value(),
        body=body,
        msg_id=request.headers.get("svix-id"),
        timestamp=request.headers.get("svix-timestamp"),
        signature_header=request.headers.get("svix-signature"),
        tolerance_seconds=settings.WEBHOOK_TOLERANCE_SECONDS,
    )
    msg_id = request.headers["svix-id"]
    # The database work is synchronous, so run it off the event loop.
    outcome = await run_in_threadpool(process_event, db, event_id=msg_id, body=body)
    return ok(
        "Duplicate event ignored." if outcome.duplicate else "Event processed.",
        WebhookResult(
            event_type=outcome.event_type,
            duplicate=outcome.duplicate,
            matched_email=outcome.matched_email,
            status_changed=outcome.status_changed,
        ),
    )
