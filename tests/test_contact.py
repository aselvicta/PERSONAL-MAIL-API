from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import ContactSubmission, EmailLog
from app.services.resend_service import ProviderErrorCode, SendResult, SendStatus
from tests.conftest import FakeResendService, FakeTurnstile, KeyedProject, make_project

URL = "/api/v1/contact"
ORIGIN = "https://portfolio.example.com"

FORM: dict[str, Any] = {
    "project": "portfolio",
    "name": "John Doe",
    "email": "john@example.com",
    "subject": "Software Development Opportunity",
    "message": "I would like to discuss a project with you.",
}


@pytest.fixture
def portfolio(db_session: Session, settings: Settings) -> KeyedProject:
    return make_project(
        db_session,
        settings,
        name="Portfolio",
        slug="portfolio",
        recipient_email="me@example.com",
        allowed_origins=[ORIGIN],
        transactional_enabled=False,
    )


def submit(client: TestClient, origin: str | None = ORIGIN, **overrides: Any):  # type: ignore[no-untyped-def]
    headers = {"Origin": origin} if origin else {}
    return client.post(URL, json={**FORM, **overrides}, headers=headers)


def test_contact_submission_is_stored_and_emailed(
    client: TestClient,
    portfolio: KeyedProject,
    fake_resend: FakeResendService,
    db_session: Session,
) -> None:
    response = submit(client)

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "sent"

    submission = db_session.scalars(select(ContactSubmission)).one()
    assert str(submission.id) == body["data"]["id"]
    assert submission.sender_email == "john@example.com"
    assert submission.status == "sent"
    assert submission.resend_message_id == "msg_fake_1"

    (email,) = fake_resend.sent
    assert list(email.to) == ["me@example.com"]  # admin-configured recipient
    assert list(email.reply_to) == ["john@example.com"]  # reply goes to the sender
    assert email.subject == "New message from your Portfolio: Software Development Opportunity"
    assert email.html and "John Doe" in email.html and "I would like to discuss" in email.html
    assert email.text and "john@example.com" in email.text

    log = db_session.scalars(select(EmailLog)).one()
    assert log.email_type == "contact_notification"
    assert log.status == "accepted"


def test_untrusted_content_is_html_escaped(
    client: TestClient, portfolio: KeyedProject, fake_resend: FakeResendService
) -> None:
    response = submit(
        client,
        name="<img src=x onerror=alert(1)>",
        message="<script>alert('xss')</script>",
    )
    assert response.status_code == 201
    html = fake_resend.sent[0].html or ""
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img src=x" not in html


def test_public_form_cannot_choose_recipient(client: TestClient, portfolio: KeyedProject) -> None:
    response = submit(client, to="victim@example.com")
    assert response.status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "not-an-email"},
        {"name": ""},
        {"message": "x" * 5001},
        {"name": "Evil\r\nBcc: victim@example.com"},
        {"subject": "Hi\nBcc: victim@example.com"},
        {"project": "NOT VALID"},
    ],
)
def test_invalid_submissions_are_rejected(
    client: TestClient, portfolio: KeyedProject, overrides: dict[str, Any]
) -> None:
    response = submit(client, **overrides)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unknown_or_disabled_projects_look_the_same(
    client: TestClient, portfolio: KeyedProject, db_session: Session
) -> None:
    unknown = submit(client, project="does-not-exist")
    assert unknown.status_code == 404

    portfolio.project.contact_enabled = False
    db_session.commit()
    assert submit(client).json() == unknown.json()

    portfolio.project.contact_enabled = True
    portfolio.project.is_active = False
    db_session.commit()
    assert submit(client).json() == unknown.json()


@pytest.mark.parametrize("origin", ["https://evil.example.com", None])
def test_origin_must_be_allowed(
    client: TestClient, portfolio: KeyedProject, fake_resend: FakeResendService, origin: str | None
) -> None:
    response = submit(client, origin=origin)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"
    assert fake_resend.sent == []


def test_project_without_origin_list_accepts_any_origin(
    client: TestClient, portfolio: KeyedProject, db_session: Session
) -> None:
    portfolio.project.allowed_origins = []
    db_session.commit()
    assert submit(client, origin="https://anything.example.com").status_code == 201


def test_honeypot_returns_fake_success_without_sending(
    client: TestClient,
    portfolio: KeyedProject,
    fake_resend: FakeResendService,
    db_session: Session,
) -> None:
    response = submit(client, website="http://spam.example.com")
    assert response.status_code == 201
    assert fake_resend.sent == []
    assert db_session.scalars(select(ContactSubmission)).all() == []


def test_per_ip_rate_limit(client: TestClient, portfolio: KeyedProject, settings: Settings) -> None:
    for _ in range(settings.CONTACT_RATE_LIMIT_PER_IP):
        assert submit(client).status_code == 201
    blocked = submit(client)
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_daily_quota_applies_to_contact(
    client: TestClient, portfolio: KeyedProject, db_session: Session
) -> None:
    portfolio.project.daily_quota = 1
    db_session.commit()
    assert submit(client).status_code == 201
    blocked = submit(client)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "DAILY_QUOTA_EXCEEDED"


def test_turnstile_is_enforced_when_enabled(
    client: TestClient,
    portfolio: KeyedProject,
    fake_turnstile: FakeTurnstile,
    db_session: Session,
) -> None:
    portfolio.project.turnstile_enabled = True
    db_session.commit()

    missing = submit(client)
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "TURNSTILE_FAILED"
    assert submit(client, turnstile_token="forged").status_code == 403
    assert submit(client, turnstile_token="valid-token").status_code == 201
    assert fake_turnstile.calls[-1] == ("valid-token", "testclient")


def test_turnstile_enabled_without_secret_fails_closed(
    client: TestClient,
    portfolio: KeyedProject,
    fake_turnstile: FakeTurnstile,
    fake_resend: FakeResendService,
    db_session: Session,
) -> None:
    portfolio.project.turnstile_enabled = True
    db_session.commit()
    fake_turnstile.configured = False
    response = submit(client, turnstile_token="valid-token")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "TURNSTILE_NOT_CONFIGURED"
    assert fake_resend.sent == []


def test_provider_failure_keeps_submission(
    client: TestClient,
    portfolio: KeyedProject,
    fake_resend: FakeResendService,
    db_session: Session,
) -> None:
    fake_resend.result = SendResult(
        status=SendStatus.REJECTED,
        error_code=ProviderErrorCode.PROVIDER_REJECTED,
        error_message="domain not verified",
    )
    response = submit(client)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "EMAIL_DELIVERY_FAILED"
    assert "domain not verified" not in response.text  # provider detail stays internal
    submission = db_session.scalars(select(ContactSubmission)).one()
    assert submission.status == "failed"


def test_acknowledgement_is_sent_when_enabled_and_contains_no_user_text(
    client: TestClient,
    portfolio: KeyedProject,
    fake_resend: FakeResendService,
    db_session: Session,
) -> None:
    portfolio.project.acknowledgement_enabled = True
    db_session.commit()

    response = submit(client, name="Buy cheap stuff at spam.example", message="SPAM CONTENT")
    assert response.status_code == 201

    _notification, ack = fake_resend.sent
    assert list(ack.to) == ["john@example.com"]
    assert list(ack.reply_to) == ["me@example.com"]
    for body in (ack.html or "", ack.text or "", ack.subject):
        assert "spam.example" not in body
        assert "SPAM CONTENT" not in body


def test_acknowledgement_disabled_by_default(
    client: TestClient, portfolio: KeyedProject, fake_resend: FakeResendService
) -> None:
    submit(client)
    assert len(fake_resend.sent) == 1


def test_backend_proxy_with_api_key_skips_origin_check(
    client: TestClient, portfolio: KeyedProject, other_project: KeyedProject
) -> None:
    ok = client.post(URL, json=FORM, headers=portfolio.headers)
    assert ok.status_code == 201

    mismatched = client.post(URL, json=FORM, headers=other_project.headers)
    assert mismatched.status_code == 403
    assert mismatched.json()["error"]["code"] == "PROJECT_MISMATCH"

    bad_key = client.post(URL, json=FORM, headers={"Authorization": "Bearer pmk_" + "x" * 43})
    assert bad_key.status_code == 401


def test_cors_preflight_for_contact(client: TestClient) -> None:
    response = client.options(
        URL,
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in response.headers


def test_cors_header_on_contact_response(client: TestClient, portfolio: KeyedProject) -> None:
    response = submit(client)
    assert response.headers["access-control-allow-origin"] == ORIGIN
