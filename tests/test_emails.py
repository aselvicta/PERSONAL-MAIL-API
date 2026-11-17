from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EmailLog
from app.services.resend_service import ProviderErrorCode, SendResult, SendStatus
from tests.conftest import FakeResendService, KeyedProject

URL = "/api/v1/emails/send"

RAW: dict[str, Any] = {
    "to": "user@example.com",
    "subject": "Welcome to CareerDocs",
    "html": "<h1>Welcome!</h1>",
    "text": "Welcome to CareerDocs.",
    "reply_to": "support@example.com",
}


def send(client: TestClient, project: KeyedProject, **overrides: Any):  # type: ignore[no-untyped-def]
    return client.post(URL, json={**RAW, **overrides}, headers=project.headers)


def test_send_raw_email(
    client: TestClient,
    keyed_project: KeyedProject,
    fake_resend: FakeResendService,
    db_session: Session,
) -> None:
    response = send(client, keyed_project)

    assert response.status_code == 202
    data = response.json()["data"]
    assert data["message_id"] == "msg_fake_1"
    assert data["status"] == "accepted"

    (email,) = fake_resend.sent
    assert list(email.to) == ["user@example.com"]
    assert email.html == "<h1>Welcome!</h1>"  # the project's own HTML is sent as-is
    assert list(email.reply_to) == ["support@example.com"]
    assert email.from_email == "noreply@mail.example.com"

    log = db_session.get(EmailLog, data["id"])
    assert log is not None and log.project_id == keyed_project.project.id


def test_sender_address_cannot_be_overridden(
    client: TestClient, keyed_project: KeyedProject, fake_resend: FakeResendService
) -> None:
    assert send(client, keyed_project, **{"from": "ceo@bank.com"}).status_code == 422
    assert send(client, keyed_project, sender_email="ceo@bank.com").status_code == 422

    assert send(client, keyed_project, sender_name="CareerDocs Team").status_code == 202
    (email,) = fake_resend.sent
    assert email.from_name == "CareerDocs Team"
    assert email.from_email == "noreply@mail.example.com"


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        ({}, "API_KEY_REQUIRED"),
        ({"Authorization": "Bearer pmk_" + "x" * 43}, "INVALID_API_KEY"),
        ({"Authorization": "Bearer not-a-key"}, "INVALID_API_KEY"),
    ],
)
def test_authentication_required(client: TestClient, headers: dict[str, str], code: str) -> None:
    response = client.post(URL, json=RAW, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == code


def test_transactional_permission_required(
    client: TestClient, keyed_project: KeyedProject, db_session: Session
) -> None:
    keyed_project.project.transactional_enabled = False
    db_session.commit()
    response = send(client, keyed_project)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TRANSACTIONAL_DISABLED"


def test_recipient_domain_allowlist(
    client: TestClient, keyed_project: KeyedProject, db_session: Session
) -> None:
    keyed_project.project.allowed_recipient_domains = ["careerdocs.example.com"]
    db_session.commit()
    blocked = send(client, keyed_project, to="someone@gmail.com")
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "RECIPIENT_NOT_ALLOWED"
    assert send(client, keyed_project, to="jane@CareerDocs.example.com").status_code == 202


@pytest.mark.parametrize(
    "overrides",
    [
        {"to": "not-an-email"},
        {"to": ["a@example.com", "b@example.com"]},
        {"subject": None},
        {"html": None, "text": None},
        {"subject": "Hi\r\nBcc: victim@example.com"},
        {"html": "x" * 200_001},
        {"template": "welcome"},  # template together with html/text
        {"variables": {"a": "b"}},  # variables without template
    ],
)
def test_invalid_requests(
    client: TestClient, keyed_project: KeyedProject, overrides: dict[str, Any]
) -> None:
    response = send(client, keyed_project, **overrides)
    assert response.status_code == 422


def test_send_with_template(
    client: TestClient, keyed_project: KeyedProject, fake_resend: FakeResendService
) -> None:
    response = client.post(
        URL,
        json={
            "to": "jane@example.com",
            "template": "password_reset",
            "variables": {
                "name": "<b>Jane</b>",
                "reset_url": "https://careerdocs.example.com/reset?token=abc&x=1",
                "expires_in_minutes": 30,
            },
        },
        headers=keyed_project.headers,
    )
    assert response.status_code == 202
    (email,) = fake_resend.sent
    assert email.subject == "Reset your CareerDocs password"  # app_name defaults to project name
    assert "&lt;b&gt;Jane&lt;/b&gt;" in (email.html or "")
    assert "https://careerdocs.example.com/reset?token=abc&amp;x=1" in (email.html or "")
    assert "30 minutes" in (email.text or "")


@pytest.mark.parametrize(
    ("variables", "fragment"),
    [
        ({"reset_url": "javascript:alert(1)"}, "reset_url must be an absolute http(s) URL"),
        ({}, "missing required variables: reset_url"),
        ({"reset_url": "https://x.example.com", "bogus": "1"}, "unknown variables: bogus"),
    ],
)
def test_template_variable_validation(
    client: TestClient,
    keyed_project: KeyedProject,
    fake_resend: FakeResendService,
    variables: dict[str, Any],
    fragment: str,
) -> None:
    response = client.post(
        URL,
        json={"to": "jane@example.com", "template": "password_reset", "variables": variables},
        headers=keyed_project.headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_TEMPLATE_VARIABLES"
    assert any(fragment in d for d in response.json()["error"]["details"])
    assert fake_resend.sent == []


def test_internal_templates_are_not_available(
    client: TestClient, keyed_project: KeyedProject
) -> None:
    response = client.post(
        URL,
        json={"to": "jane@example.com", "template": "contact_notification", "variables": {}},
        headers=keyed_project.headers,
    )
    assert response.status_code == 422


def test_project_rate_limit(
    client: TestClient, keyed_project: KeyedProject, db_session: Session
) -> None:
    keyed_project.project.rate_limit = 2
    db_session.commit()
    assert send(client, keyed_project).status_code == 202
    assert send(client, keyed_project).status_code == 202
    blocked = send(client, keyed_project)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"


def test_daily_quota(client: TestClient, keyed_project: KeyedProject, db_session: Session) -> None:
    keyed_project.project.daily_quota = 1
    db_session.commit()
    assert send(client, keyed_project).status_code == 202
    blocked = send(client, keyed_project)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "DAILY_QUOTA_EXCEEDED"


@pytest.mark.parametrize(
    ("result", "http_status", "code"),
    [
        (
            SendResult(SendStatus.REJECTED, None, ProviderErrorCode.PROVIDER_REJECTED, "bad"),
            502,
            "EMAIL_DELIVERY_FAILED",
        ),
        (
            SendResult(SendStatus.TIMEOUT, None, ProviderErrorCode.PROVIDER_TIMEOUT, "slow"),
            504,
            "EMAIL_PROVIDER_TIMEOUT",
        ),
        (
            SendResult(SendStatus.UNAVAILABLE, None, ProviderErrorCode.PROVIDER_UNAVAILABLE, "x"),
            503,
            "EMAIL_PROVIDER_UNAVAILABLE",
        ),
        (
            SendResult(SendStatus.MISCONFIGURED, None, ProviderErrorCode.PROVIDER_AUTH_FAILED, "x"),
            503,
            "SERVICE_MISCONFIGURED",
        ),
    ],
)
def test_provider_errors_are_mapped_and_logged(
    client: TestClient,
    keyed_project: KeyedProject,
    fake_resend: FakeResendService,
    db_session: Session,
    result: SendResult,
    http_status: int,
    code: str,
) -> None:
    fake_resend.result = result
    response = send(client, keyed_project)

    assert response.status_code == http_status
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == code
    log = db_session.scalars(select(EmailLog)).one()
    assert log.status == "failed"
    assert log.error_code == result.error_code
    assert body["error"]["details"]["id"] == str(log.id)


def test_project_isolation_for_email_logs(
    client: TestClient, keyed_project: KeyedProject, other_project: KeyedProject
) -> None:
    email_id = send(client, keyed_project).json()["data"]["id"]

    own = client.get(f"/api/v1/emails/{email_id}", headers=keyed_project.headers)
    assert own.status_code == 200
    assert own.json()["data"]["recipient"] == "user@example.com"

    foreign = client.get(f"/api/v1/emails/{email_id}", headers=other_project.headers)
    assert foreign.status_code == 404

    assert client.get("/api/v1/emails", headers=keyed_project.headers).json()["data"]["total"] == 1
    assert client.get("/api/v1/emails", headers=other_project.headers).json()["data"]["total"] == 0


def test_list_emails_filters_and_paginates(client: TestClient, keyed_project: KeyedProject) -> None:
    for _ in range(3):
        send(client, keyed_project)
    page = client.get("/api/v1/emails?limit=2&offset=0", headers=keyed_project.headers).json()
    assert page["data"]["total"] == 3
    assert len(page["data"]["items"]) == 2
    filtered = client.get("/api/v1/emails?status=failed", headers=keyed_project.headers).json()
    assert filtered["data"]["total"] == 0
    assert client.get("/api/v1/emails?limit=1000", headers=keyed_project.headers).status_code == 422
