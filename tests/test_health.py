from __future__ import annotations

from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.database.session import get_db


def test_application_starts_and_serves_openapi(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Personal Mail API"


def test_health_reports_ok_with_database(client: TestClient, settings: Settings) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] == {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": "test",
        "database": "ok",
        "email_provider": "configured",
    }


def test_health_accepts_head_requests(client: TestClient) -> None:
    response = client.head("/health")

    assert response.status_code == 200
    assert response.content == b""


def test_health_does_not_expose_secrets(client: TestClient, settings: Settings) -> None:
    raw = client.get("/health").text
    assert settings.JWT_SECRET_KEY.get_secret_value() not in raw
    assert settings.RESEND_API_KEY is not None
    assert settings.RESEND_API_KEY.get_secret_value() not in raw
    assert "postgres:postgres" not in raw
    assert "5433" not in raw


def test_health_returns_503_when_database_unavailable(app: FastAPI) -> None:
    unreachable = create_engine(
        "postgresql+psycopg://user:secret-password@127.0.0.1:1/nowhere",
        connect_args={"connect_timeout": 1},
    )

    def broken_db() -> Iterator[Session]:
        with Session(unreachable) as session:
            yield session

    app.dependency_overrides[get_db] = broken_db
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["success"] is False
    assert body["data"]["database"] == "unavailable"
    assert "secret-password" not in response.text


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {
        "success": False,
        "message": "Not Found",
        "error": {"code": "NOT_FOUND"},
    }


def test_unhandled_errors_do_not_leak_details(app: FastAPI) -> None:
    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("internal detail: password=hunter2")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "hunter2" not in response.text
