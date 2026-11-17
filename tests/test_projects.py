from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApiKey, EmailLog, Project
from tests.conftest import KeyedProject

BASE = "/api/v1/admin/projects"

PORTFOLIO: dict[str, Any] = {
    "name": "Portfolio",
    "slug": "portfolio",
    "recipient_email": "me@example.com",
    "allowed_origins": ["https://Portfolio.example.com/"],
}


def create(client: TestClient, headers: dict[str, str], **overrides: Any):  # type: ignore[no-untyped-def]
    return client.post(BASE, json={**PORTFOLIO, **overrides}, headers=headers)


def test_create_project_returns_api_key_once(
    client: TestClient, admin_headers: dict[str, str], db_session: Session
) -> None:
    response = create(client, admin_headers)

    assert response.status_code == 201
    data = response.json()["data"]
    project, key = data["project"], data["api_key"]
    assert project["slug"] == "portfolio"
    assert project["allowed_origins"] == ["https://portfolio.example.com"]
    assert project["transactional_enabled"] is False  # secure default
    assert key["api_key"].startswith("pmk_")
    assert key["key_prefix"] == key["api_key"][:12]

    # Only the hash is stored.
    stored = db_session.scalars(select(ApiKey)).one()
    assert stored.key_hash != key["api_key"]

    # The key is never shown again.
    project_id = project["id"]
    for path in (f"{BASE}/{project_id}", f"{BASE}/{project_id}/api-keys", BASE):
        text = client.get(path, headers=admin_headers).text
        assert key["api_key"] not in text
        assert stored.key_hash not in text


def test_duplicate_slug_conflicts(client: TestClient, admin_headers: dict[str, str]) -> None:
    assert create(client, admin_headers).status_code == 201
    response = create(client, admin_headers, name="Other")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PROJECT_SLUG_TAKEN"


@pytest.mark.parametrize(
    "overrides",
    [
        {"slug": "Not A Slug"},
        {"slug": "-bad"},
        {"recipient_email": "not-an-email"},
        {"allowed_origins": ["https://example.com/path"]},
        {"allowed_origins": ["javascript:alert(1)"]},
        {"allowed_recipient_domains": ["not a domain"]},
        {"name": "Evil\r\nBcc: x@example.com"},
        {"sender_name": "Evil\nBcc: x@example.com"},
        {"rate_limit": 0},
        {"daily_quota": -1},
    ],
)
def test_invalid_project_data_is_rejected(
    client: TestClient, admin_headers: dict[str, str], overrides: dict[str, Any]
) -> None:
    response = create(client, admin_headers, **overrides)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_sender_must_use_an_allowed_domain(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    # Test settings: DEFAULT_FROM_EMAIL=noreply@mail.example.com
    rejected = create(client, admin_headers, sender_email="me@gmail.com")
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "SENDER_DOMAIN_NOT_ALLOWED"

    accepted = create(client, admin_headers, sender_email="portfolio@mail.example.com")
    assert accepted.status_code == 201


def test_list_get_update_project(client: TestClient, admin_headers: dict[str, str]) -> None:
    project_id = create(client, admin_headers).json()["data"]["project"]["id"]

    listing = client.get(BASE, headers=admin_headers).json()["data"]
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == project_id

    response = client.patch(
        f"{BASE}/{project_id}",
        json={"transactional_enabled": True, "rate_limit": 10, "description": "My site"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    updated = response.json()["data"]
    assert updated["transactional_enabled"] is True
    assert updated["rate_limit"] == 10
    assert updated["name"] == "Portfolio"  # untouched

    assert (
        client.patch(f"{BASE}/{project_id}", json={"name": None}, headers=admin_headers).status_code
        == 400
    )


def test_unknown_project_is_404(client: TestClient, admin_headers: dict[str, str]) -> None:
    missing = "00000000-0000-0000-0000-000000000001"
    assert client.get(f"{BASE}/{missing}", headers=admin_headers).status_code == 404
    assert client.get(f"{BASE}/not-a-uuid", headers=admin_headers).status_code == 422


def test_disable_and_enable_project(
    client: TestClient, admin_headers: dict[str, str], keyed_project: KeyedProject
) -> None:
    pid = keyed_project.project.id
    assert (
        client.post(f"{BASE}/{pid}/disable", headers=admin_headers).json()["data"]["is_active"]
        is False
    )

    blocked = client.get("/api/v1/emails", headers=keyed_project.headers)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "PROJECT_DISABLED"

    assert (
        client.post(f"{BASE}/{pid}/enable", headers=admin_headers).json()["data"]["is_active"]
        is True
    )
    assert client.get("/api/v1/emails", headers=keyed_project.headers).status_code == 200


def test_regenerate_key_revokes_previous_key(
    client: TestClient, admin_headers: dict[str, str], keyed_project: KeyedProject
) -> None:
    pid = keyed_project.project.id
    response = client.post(f"{BASE}/{pid}/api-keys", headers=admin_headers)
    assert response.status_code == 201
    new_key = response.json()["data"]["api_key"]

    old = client.get("/api/v1/emails", headers=keyed_project.headers)
    assert old.status_code == 401
    assert old.json()["error"]["code"] == "INVALID_API_KEY"
    new = client.get("/api/v1/emails", headers={"Authorization": f"Bearer {new_key}"})
    assert new.status_code == 200

    keys = client.get(f"{BASE}/{pid}/api-keys", headers=admin_headers).json()["data"]
    assert [k["is_active"] for k in keys] == [True, False]
    assert keys[1]["revoked_at"] is not None


def test_revoke_key(
    client: TestClient,
    admin_headers: dict[str, str],
    keyed_project: KeyedProject,
    other_project: KeyedProject,
) -> None:
    pid = keyed_project.project.id
    key_id = client.get(f"{BASE}/{pid}/api-keys", headers=admin_headers).json()["data"][0]["id"]

    # A key can only be revoked through its own project.
    wrong = client.delete(
        f"{BASE}/{other_project.project.id}/api-keys/{key_id}", headers=admin_headers
    )
    assert wrong.status_code == 404

    response = client.delete(f"{BASE}/{pid}/api-keys/{key_id}", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["data"]["is_active"] is False
    assert client.get("/api/v1/emails", headers=keyed_project.headers).status_code == 401


def test_usage_and_admin_log_views(
    client: TestClient,
    admin_headers: dict[str, str],
    keyed_project: KeyedProject,
) -> None:
    sent = client.post(
        "/api/v1/emails/send",
        json={"to": "user@example.com", "subject": "Hi", "text": "Hello"},
        headers=keyed_project.headers,
    )
    assert sent.status_code == 202
    pid = keyed_project.project.id

    usage = client.get(f"{BASE}/{pid}/usage", headers=admin_headers).json()["data"]
    assert usage["emails_total"] == 1
    assert usage["emails_today"] == 1
    assert usage["daily_quota_remaining"] == usage["daily_quota"] - 1
    assert usage["emails_by_status"] == {"accepted": 1}
    assert usage["emails_by_type"] == {"transactional": 1}
    assert usage["api_key_last_used_at"] is not None

    logs = client.get(f"{BASE}/{pid}/emails", headers=admin_headers).json()["data"]
    assert logs["total"] == 1
    email_id = logs["items"][0]["id"]
    detail = client.get(f"{BASE}/{pid}/emails/{email_id}", headers=admin_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["events"] == []

    submissions = client.get(f"{BASE}/{pid}/contact-submissions", headers=admin_headers)
    assert submissions.json()["data"]["total"] == 0


def test_delete_project_cascades(
    client: TestClient,
    admin_headers: dict[str, str],
    keyed_project: KeyedProject,
    db_session: Session,
) -> None:
    client.post(
        "/api/v1/emails/send",
        json={"to": "user@example.com", "subject": "Hi", "text": "Hello"},
        headers=keyed_project.headers,
    )
    response = client.delete(f"{BASE}/{keyed_project.project.id}", headers=admin_headers)
    assert response.status_code == 200
    assert db_session.scalars(select(Project)).all() == []
    assert db_session.scalars(select(EmailLog)).all() == []
    assert db_session.scalars(select(ApiKey)).all() == []
