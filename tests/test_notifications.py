from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EmailLog
from tests.conftest import FakeResendService, KeyedProject

URL = "/api/v1/notifications"
BODY: dict[str, Any] = {
    "type": "user.registered",
    "subject": "New user registration",
    "message": "A new user just signed up.",
    "details": {"Email": "jane@example.com", "Plan": "Pro", "Seats": 3},
}


def test_notification_goes_to_configured_recipient(
    client: TestClient,
    keyed_project: KeyedProject,
    fake_resend: FakeResendService,
    db_session: Session,
) -> None:
    response = client.post(URL, json=BODY, headers=keyed_project.headers)

    assert response.status_code == 202
    (email,) = fake_resend.sent
    assert list(email.to) == ["owner@example.com"]
    assert email.subject == "[CareerDocs] New user registration"
    assert "user.registered" in (email.html or "")
    assert "jane@example.com" in (email.html or "")
    assert "Seats: 3" in (email.text or "")
    log = db_session.scalars(select(EmailLog)).one()
    assert log.email_type == "notification"


def test_notification_recipient_cannot_be_chosen(
    client: TestClient, keyed_project: KeyedProject
) -> None:
    response = client.post(
        URL, json={**BODY, "to": "victim@example.com"}, headers=keyed_project.headers
    )
    assert response.status_code == 422


def test_notifications_permission(
    client: TestClient, keyed_project: KeyedProject, db_session: Session
) -> None:
    keyed_project.project.notifications_enabled = False
    db_session.commit()
    response = client.post(URL, json=BODY, headers=keyed_project.headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOTIFICATIONS_DISABLED"


def test_notification_requires_api_key(client: TestClient) -> None:
    assert client.post(URL, json=BODY).status_code == 401


def test_notification_details_are_escaped(
    client: TestClient, keyed_project: KeyedProject, fake_resend: FakeResendService
) -> None:
    body = {**BODY, "details": {"<b>key</b>": "<script>x</script>"}}
    assert client.post(URL, json=body, headers=keyed_project.headers).status_code == 202
    html = fake_resend.sent[0].html or ""
    assert "<script>" not in html and "<b>key</b>" not in html


@pytest.mark.parametrize(
    "overrides",
    [
        {"type": "Has Spaces"},
        {"subject": "a\nb"},
        {"message": ""},
        {"details": {f"k{i}": i for i in range(26)}},
    ],
)
def test_invalid_notifications(
    client: TestClient, keyed_project: KeyedProject, overrides: dict[str, Any]
) -> None:
    response = client.post(URL, json={**BODY, **overrides}, headers=keyed_project.headers)
    assert response.status_code == 422
