from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import EmailEvent, EmailLog, EmailStatus, EmailType
from app.services.webhook_service import WebhookVerificationError, verify_signature
from tests.conftest import KeyedProject

URL = "/api/v1/webhooks/resend"


def sign(secret: str, msg_id: str, timestamp: int, body: bytes) -> str:
    key = base64.b64decode(secret.removeprefix("whsec_"))
    digest = hmac.new(key, f"{msg_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


def post_event(
    client: TestClient,
    settings: Settings,
    payload: dict[str, Any],
    *,
    msg_id: str | None = None,
    timestamp: int | None = None,
    signature: str | None = None,
):  # type: ignore[no-untyped-def]
    assert settings.RESEND_WEBHOOK_SECRET is not None
    body = json.dumps(payload).encode()
    msg_id = msg_id or f"msg_{uuid.uuid4().hex}"
    timestamp = timestamp or int(time.time())
    signature = signature or sign(
        settings.RESEND_WEBHOOK_SECRET.get_secret_value(), msg_id, timestamp, body
    )
    return client.post(
        URL,
        content=body,
        headers={
            "svix-id": msg_id,
            "svix-timestamp": str(timestamp),
            "svix-signature": signature,
            "content-type": "application/json",
        },
    )


def event(event_type: str, email_id: str, **data: Any) -> dict[str, Any]:
    return {
        "type": event_type,
        "created_at": "2026-11-17T10:00:00.000Z",
        "data": {"email_id": email_id, "to": ["user@example.com"], **data},
    }


@pytest.fixture
def email_log(db_session: Session, keyed_project: KeyedProject) -> EmailLog:
    log = EmailLog(
        project_id=keyed_project.project.id,
        recipient="user@example.com",
        subject="Hi",
        email_type=EmailType.TRANSACTIONAL.value,
        status=EmailStatus.ACCEPTED.value,
        resend_message_id="re-msg-123",
    )
    db_session.add(log)
    db_session.commit()
    return log


def test_delivered_event_updates_status(
    client: TestClient, settings: Settings, email_log: EmailLog, db_session: Session
) -> None:
    response = post_event(client, settings, event("email.delivered", "re-msg-123"))

    assert response.status_code == 200
    assert response.json()["data"] == {
        "event_type": "email.delivered",
        "duplicate": False,
        "matched_email": True,
        "status_changed": True,
    }
    db_session.refresh(email_log)
    assert email_log.status == "delivered"
    stored = db_session.scalars(select(EmailEvent)).one()
    assert stored.email_log_id == email_log.id
    assert stored.event_payload["type"] == "email.delivered"


def test_bounce_records_reason(
    client: TestClient, settings: Settings, email_log: EmailLog, db_session: Session
) -> None:
    post_event(
        client,
        settings,
        event("email.bounced", "re-msg-123", bounce={"message": "Mailbox does not exist"}),
    )
    db_session.refresh(email_log)
    assert email_log.status == "bounced"
    assert email_log.error_code == "BOUNCED"
    assert email_log.error_message == "Mailbox does not exist"


def test_duplicate_events_are_processed_once(
    client: TestClient, settings: Settings, email_log: EmailLog, db_session: Session
) -> None:
    payload = event("email.delivered", "re-msg-123")
    first = post_event(client, settings, payload, msg_id="msg_fixed")
    second = post_event(client, settings, payload, msg_id="msg_fixed")

    assert first.json()["data"]["duplicate"] is False
    assert second.status_code == 200
    assert second.json()["data"]["duplicate"] is True
    assert len(db_session.scalars(select(EmailEvent)).all()) == 1


def test_status_never_moves_backwards(
    client: TestClient, settings: Settings, email_log: EmailLog, db_session: Session
) -> None:
    post_event(client, settings, event("email.delivered", "re-msg-123"))
    late = post_event(client, settings, event("email.sent", "re-msg-123"))
    assert late.json()["data"]["status_changed"] is False
    db_session.refresh(email_log)
    assert email_log.status == "delivered"

    # ...but a later complaint does override delivery.
    post_event(client, settings, event("email.complained", "re-msg-123"))
    db_session.refresh(email_log)
    assert email_log.status == "complained"


def test_unknown_email_and_event_types_are_accepted_safely(
    client: TestClient, settings: Settings, email_log: EmailLog, db_session: Session
) -> None:
    unknown_email = post_event(client, settings, event("email.delivered", "not-ours"))
    assert unknown_email.status_code == 200
    assert unknown_email.json()["data"]["matched_email"] is False

    unknown_type = post_event(client, settings, event("email.opened", "re-msg-123"))
    assert unknown_type.status_code == 200
    assert unknown_type.json()["data"]["status_changed"] is False
    db_session.refresh(email_log)
    assert email_log.status == "accepted"


def test_email_detail_includes_events(
    client: TestClient,
    settings: Settings,
    email_log: EmailLog,
    keyed_project: KeyedProject,
) -> None:
    post_event(client, settings, event("email.sent", "re-msg-123"))
    post_event(client, settings, event("email.delivered", "re-msg-123"))
    detail = client.get(f"/api/v1/emails/{email_log.id}", headers=keyed_project.headers).json()
    assert detail["data"]["status"] == "delivered"
    assert [e["event_type"] for e in detail["data"]["events"]] == ["email.sent", "email.delivered"]


@pytest.mark.parametrize(
    "tamper",
    [
        {"signature": "v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="},
        {"signature": "v0,whatever"},
        {"timestamp": int(time.time()) - 3600},
        {"timestamp": int(time.time()) + 3600},
    ],
)
def test_invalid_signatures_are_rejected(
    client: TestClient,
    settings: Settings,
    email_log: EmailLog,
    db_session: Session,
    tamper: dict[str, Any],
) -> None:
    payload = event("email.delivered", "re-msg-123")
    if "timestamp" in tamper and "signature" not in tamper:
        assert settings.RESEND_WEBHOOK_SECRET is not None
        body = json.dumps(payload).encode()
        tamper["signature"] = sign(
            settings.RESEND_WEBHOOK_SECRET.get_secret_value(), "m1", tamper["timestamp"], body
        )
        tamper["msg_id"] = "m1"
    response = post_event(client, settings, payload, **tamper)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_WEBHOOK_SIGNATURE"
    db_session.refresh(email_log)
    assert email_log.status == "accepted"
    assert db_session.scalars(select(EmailEvent)).all() == []


def test_modified_body_is_rejected(client: TestClient, settings: Settings) -> None:
    assert settings.RESEND_WEBHOOK_SECRET is not None
    ts = int(time.time())
    signature = sign(settings.RESEND_WEBHOOK_SECRET.get_secret_value(), "m1", ts, b'{"a":1}')
    response = client.post(
        URL,
        content=b'{"a":2}',
        headers={"svix-id": "m1", "svix-timestamp": str(ts), "svix-signature": signature},
    )
    assert response.status_code == 401


def test_missing_headers_are_rejected(client: TestClient) -> None:
    response = client.post(URL, json=event("email.delivered", "x"))
    assert response.status_code == 401


def test_rotated_secrets_with_multiple_signatures(settings: Settings) -> None:
    assert settings.RESEND_WEBHOOK_SECRET is not None
    secret = settings.RESEND_WEBHOOK_SECRET.get_secret_value()
    ts = int(time.time())
    good = sign(secret, "m1", ts, b"{}")
    verify_signature(
        secret=secret,
        body=b"{}",
        msg_id="m1",
        timestamp=str(ts),
        signature_header=f"v1,b2xkLXNpZ25hdHVyZQ== {good}",
        tolerance_seconds=300,
    )
    with pytest.raises(WebhookVerificationError):
        verify_signature(
            secret=secret,
            body=b"{}",
            msg_id="m1",
            timestamp="not-a-number",
            signature_header=good,
            tolerance_seconds=300,
        )


def test_signed_but_malformed_payload_is_400(client: TestClient, settings: Settings) -> None:
    assert settings.RESEND_WEBHOOK_SECRET is not None
    ts = int(time.time())
    body = b"not json"
    signature = sign(settings.RESEND_WEBHOOK_SECRET.get_secret_value(), "m2", ts, body)
    response = client.post(
        URL,
        content=body,
        headers={"svix-id": "m2", "svix-timestamp": str(ts), "svix-signature": signature},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_WEBHOOK_PAYLOAD"


def test_webhook_rejected_when_secret_not_configured(app: FastAPI, settings: Settings) -> None:
    app.dependency_overrides[get_settings] = lambda: settings.model_copy(
        update={"RESEND_WEBHOOK_SECRET": None}
    )
    with TestClient(app) as client:
        response = client.post(URL, json=event("email.delivered", "x"))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "WEBHOOK_NOT_CONFIGURED"
