from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Administrator
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD


def login(client: TestClient, email: str = ADMIN_EMAIL, password: str = ADMIN_PASSWORD):  # type: ignore[no-untyped-def]
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_admin_can_log_in_and_use_token(client: TestClient, admin: Administrator) -> None:
    response = login(client)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert me.status_code == 200
    assert me.json()["data"]["email"] == ADMIN_EMAIL
    assert "hashed_password" not in me.text


def test_login_email_is_case_insensitive(client: TestClient, admin: Administrator) -> None:
    assert login(client, email=ADMIN_EMAIL.upper()).status_code == 200


@pytest.mark.parametrize(
    ("email", "password"),
    [(ADMIN_EMAIL, "wrong-password-123"), ("nobody@example.com", ADMIN_PASSWORD)],
)
def test_bad_credentials_get_identical_generic_error(
    client: TestClient, admin: Administrator, email: str, password: str
) -> None:
    response = login(client, email, password)
    assert response.status_code == 401
    assert response.json() == {
        "success": False,
        "message": "Invalid email or password.",
        "error": {"code": "INVALID_CREDENTIALS"},
    }


def test_inactive_admin_cannot_log_in_or_use_token(
    client: TestClient, admin: Administrator, admin_headers: dict[str, str], db_session: Session
) -> None:
    admin.is_active = False
    db_session.commit()
    assert login(client).status_code == 401
    assert client.get("/api/v1/auth/me", headers=admin_headers).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-jwt"}, {"Authorization": "Basic abc"}],
)
def test_admin_endpoints_require_valid_token(client: TestClient, headers: dict[str, str]) -> None:
    for method, path in [
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/admin/projects"),
        ("POST", "/api/v1/admin/projects"),
    ]:
        response = client.request(method, path, headers=headers, json={})
        assert response.status_code == 401, (method, path)
        assert response.json()["success"] is False


def test_project_api_key_cannot_access_admin_endpoints(
    client: TestClient,
    keyed_project,  # type: ignore[no-untyped-def]
) -> None:
    response = client.get("/api/v1/admin/projects", headers=keyed_project.headers)
    assert response.status_code == 401


def test_login_is_rate_limited(
    client: TestClient, admin: Administrator, settings: Settings
) -> None:
    for _ in range(settings.LOGIN_RATE_LIMIT_PER_IP):
        assert login(client, password="wrong-password-123").status_code == 401
    blocked = login(client)  # even the correct password is blocked now
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert int(blocked.headers["Retry-After"]) > 0


def test_create_admin_cli(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import create_admin as cli

    @contextmanager
    def session_factory() -> Iterator[Session]:
        yield db_session

    monkeypatch.setattr(cli, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setenv("ADMIN_PASSWORD", "a-long-and-strong-password")

    assert cli.main(["--email", "Owner@Example.com"]) == 0
    admin = db_session.scalars(select(Administrator)).one()
    assert admin.email == "owner@example.com"
    assert admin.hashed_password.startswith("$argon2id$")

    assert cli.main(["--email", "owner@example.com"]) == 1  # already exists
    monkeypatch.setenv("ADMIN_PASSWORD", "another-strong-password!")
    assert cli.main(["--email", "owner@example.com", "--reset-password"]) == 0
    monkeypatch.setenv("ADMIN_PASSWORD", "weak")
    assert cli.main(["--email", "new@example.com"]) == 2
    assert "a-long-and-strong-password" not in capsys.readouterr().out


def test_ensure_admin_is_idempotent_and_syncs_password(db_session: Session) -> None:
    from app.core.security import verify_password
    from app.services.auth_service import ensure_admin

    assert ensure_admin(db_session, "Boss@Example.com", "first-strong-password") == "created"
    assert ensure_admin(db_session, "boss@example.com", "first-strong-password") == "unchanged"

    admin = db_session.scalars(select(Administrator)).one()
    admin.is_active = False
    db_session.commit()
    assert ensure_admin(db_session, "boss@example.com", "second-strong-password") == "updated"
    db_session.refresh(admin)
    assert admin.is_active is True
    assert verify_password("second-strong-password", admin.hashed_password)
    assert not verify_password("first-strong-password", admin.hashed_password)


def test_bootstrap_admin_script(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: Settings,
) -> None:
    from pydantic import SecretStr

    from scripts import bootstrap_admin as boot

    @contextmanager
    def session_factory() -> Iterator[Session]:
        yield db_session

    monkeypatch.setattr(boot, "get_sessionmaker", lambda: session_factory)

    def run(**overrides: object) -> int:
        monkeypatch.setattr(boot, "get_settings", lambda: settings.model_copy(update=overrides))
        return boot.main()

    assert run() == 0  # nothing configured: skip
    assert db_session.scalars(select(Administrator)).all() == []
    assert run(ADMIN_EMAIL="ops@example.com") == 1  # password missing
    assert run(ADMIN_EMAIL="ops@example.com", ADMIN_PASSWORD=SecretStr("weak")) == 1
    password = SecretStr("render-bootstrap-password")
    assert run(ADMIN_EMAIL="ops@example.com", ADMIN_PASSWORD=password) == 0
    assert run(ADMIN_EMAIL="ops@example.com", ADMIN_PASSWORD=password) == 0
    out = capsys.readouterr().out
    assert "ops@example.com created" in out and "ops@example.com unchanged" in out
    assert "render-bootstrap-password" not in out
    assert db_session.scalars(select(Administrator)).one().email == "ops@example.com"
