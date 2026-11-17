"""Resend webhook verification and processing.

Resend signs webhooks with Svix. Verification follows the Svix scheme:

* signed content: ``{svix-id}.{svix-timestamp}.{raw body}``
* key: base64-decoded part of the ``whsec_...`` signing secret
* signature: base64 HMAC-SHA256. The ``svix-signature`` header may hold
  several space-separated ``v1,<sig>`` entries (during secret rotation).
* the timestamp must be within ``WEBHOOK_TOLERANCE_SECONDS`` of now, which
  limits replay.

Processing is idempotent. The ``svix-id`` is stored in the unique
``email_events.provider_event_id`` column, so redelivered events are
detected and ignored. Statuses never move backwards: a late
``email.sent`` cannot overwrite ``delivered``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import EmailEvent, EmailLog, EmailStatus

logger = logging.getLogger(__name__)


class WebhookVerificationError(AppError):
    status_code = 401
    code = "INVALID_WEBHOOK_SIGNATURE"
    message = "Webhook signature verification failed."


class InvalidWebhookPayloadError(AppError):
    code = "INVALID_WEBHOOK_PAYLOAD"
    message = "Webhook payload is invalid."


EVENT_STATUS: dict[str, EmailStatus] = {
    "email.sent": EmailStatus.SENT,
    "email.delivered": EmailStatus.DELIVERED,
    "email.delivery_delayed": EmailStatus.DELIVERY_DELAYED,
    "email.bounced": EmailStatus.BOUNCED,
    "email.complained": EmailStatus.COMPLAINED,
    "email.failed": EmailStatus.FAILED,
    "email.suppressed": EmailStatus.FAILED,
}

# Higher rank wins. Final states outrank transient ones.
STATUS_RANK: dict[str, int] = {
    EmailStatus.PENDING: 0,
    EmailStatus.ACCEPTED: 1,
    EmailStatus.SENT: 2,
    EmailStatus.DELIVERY_DELAYED: 3,
    EmailStatus.DELIVERED: 4,
    EmailStatus.FAILED: 5,
    EmailStatus.BOUNCED: 5,
    EmailStatus.COMPLAINED: 6,
}


def _decode_secret(secret: str) -> bytes:
    raw = secret.removeprefix("whsec_")
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return raw.encode()


def verify_signature(
    *,
    secret: str,
    body: bytes,
    msg_id: str | None,
    timestamp: str | None,
    signature_header: str | None,
    tolerance_seconds: int,
    now: float | None = None,
) -> None:
    """Raise WebhookVerificationError unless the request is authentic and fresh."""
    if not (msg_id and timestamp and signature_header):
        raise WebhookVerificationError("Missing webhook signature headers.")
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise WebhookVerificationError("Invalid webhook timestamp.") from exc
    current = time.time() if now is None else now
    if abs(current - ts) > tolerance_seconds:
        raise WebhookVerificationError("Webhook timestamp is outside the allowed tolerance.")

    signed = f"{msg_id}.{timestamp}.".encode() + body
    expected = base64.b64encode(
        hmac.new(_decode_secret(secret), signed, hashlib.sha256).digest()
    ).decode()

    for entry in signature_header.split():
        version, _, sig = entry.partition(",")
        if version == "v1" and hmac.compare_digest(sig, expected):
            return
    raise WebhookVerificationError()


@dataclass(frozen=True, slots=True)
class WebhookOutcome:
    duplicate: bool
    event_type: str
    matched_email: bool
    status_changed: bool


def process_event(db: Session, *, event_id: str, body: bytes) -> WebhookOutcome:
    try:
        payload: Any = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidWebhookPayloadError() from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("type"), str):
        raise InvalidWebhookPayloadError()

    event_type: str = payload["type"][:64]
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    message_id = data.get("email_id") if isinstance(data.get("email_id"), str) else None

    log = (
        db.scalar(
            select(EmailLog).where(EmailLog.resend_message_id == message_id).with_for_update()
        )
        if message_id
        else None
    )

    inserted = db.execute(
        insert(EmailEvent)
        .values(
            email_log_id=log.id if log else None,
            event_type=event_type,
            provider_event_id=event_id[:255],
            event_payload=payload,
        )
        .on_conflict_do_nothing(index_elements=[EmailEvent.provider_event_id])
        .returning(EmailEvent.id)
    ).scalar_one_or_none()

    if inserted is None:
        db.rollback()
        logger.info("Duplicate webhook event ignored id=%s", event_id)
        return WebhookOutcome(True, event_type, log is not None, False)

    changed = False
    new_status = EVENT_STATUS.get(event_type)
    if log is not None and new_status is not None:
        if STATUS_RANK.get(new_status, 0) > STATUS_RANK.get(log.status, 0):
            log.status = new_status.value
            changed = True
            if new_status in {EmailStatus.BOUNCED, EmailStatus.FAILED, EmailStatus.COMPLAINED}:
                log.error_code = event_type.removeprefix("email.").upper()
                log.error_message = _event_reason(data)
    elif log is None:
        logger.info("Webhook %s references an unknown email", event_type)

    db.commit()
    return WebhookOutcome(False, event_type, log is not None, changed)


def _event_reason(data: dict[str, Any]) -> str | None:
    for key in ("bounce", "failed", "suppressed"):
        detail = data.get(key)
        if isinstance(detail, dict):
            text = detail.get("message") or detail.get("reason") or detail.get("type")
            if text:
                return str(text)[:1000]
    return None
