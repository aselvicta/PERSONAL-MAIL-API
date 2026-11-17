from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.dependencies import get_client_ip
from app.core.config import Settings, get_settings
from app.core.exceptions import RateLimitExceededError
from app.models import RateLimitBucket
from app.services.rate_limiter import RateLimit, RateLimiter
from tests.conftest import KeyedProject

# --- Rate limiter -------------------------------------------------------------


def test_rate_limiter_counts_and_blocks(db_session: Session, settings: Settings) -> None:
    limiter = RateLimiter(db_session, settings)
    rule = RateLimit("test:key", limit=3, window_seconds=60)
    for _ in range(3):
        limiter.hit(rule)
    with pytest.raises(RateLimitExceededError) as exc_info:
        limiter.hit(rule)
    retry_after = int((exc_info.value.headers or {})["Retry-After"])
    assert 1 <= retry_after <= 60
    bucket = db_session.scalars(select(RateLimitBucket)).one()
    assert bucket.count == 4


def test_rate_limits_are_independent_per_key(db_session: Session, settings: Settings) -> None:
    limiter = RateLimiter(db_session, settings)
    limiter.hit(RateLimit("a", 1, 60))
    limiter.hit(RateLimit("b", 1, 60))
    with pytest.raises(RateLimitExceededError):
        limiter.hit(RateLimit("a", 1, 60))


def test_rate_limiting_can_be_disabled(db_session: Session, settings: Settings) -> None:
    limiter = RateLimiter(db_session, settings.model_copy(update={"RATE_LIMIT_ENABLED": False}))
    for _ in range(5):
        limiter.hit(RateLimit("x", 1, 60))
    assert db_session.scalars(select(RateLimitBucket)).all() == []


# --- Client IP ----------------------------------------------------------------


def _request(xff: str | None, peer: str = "10.0.0.1") -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


@pytest.mark.parametrize(
    ("hops", "xff", "expected"),
    [
        (0, "1.2.3.4", "10.0.0.1"),  # no trusted proxy: ignore the header
        (1, "1.2.3.4", "1.2.3.4"),
        (1, "6.6.6.6, 1.2.3.4", "1.2.3.4"),  # spoofed left-most entry ignored
        (2, "6.6.6.6, 1.2.3.4, 172.16.0.1", "1.2.3.4"),
        (1, None, "10.0.0.1"),
        (1, "garbage", "10.0.0.1"),
    ],
)
def test_client_ip_respects_trusted_proxy_count(
    settings: Settings, hops: int, xff: str | None, expected: str
) -> None:
    configured = settings.model_copy(update={"TRUSTED_PROXY_COUNT": hops})
    assert get_client_ip(_request(xff), configured) == expected


# --- Middleware ---------------------------------------------------------------


def test_oversized_body_is_rejected(app: FastAPI, settings: Settings) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/contact",
            content=b"x" * (settings.MAX_REQUEST_BODY_BYTES + 1),
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_streamed_oversized_body_is_rejected(app: FastAPI, settings: Settings) -> None:
    def chunks():  # type: ignore[no-untyped-def]
        for _ in range(settings.MAX_REQUEST_BODY_BYTES // 1024 + 2):
            yield b"x" * 1024

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/notifications", content=chunks(), headers={"content-type": "application/json"}
        )
    assert response.status_code == 413


def test_security_headers(client: TestClient) -> None:
    response = client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"


def test_global_cors_does_not_open_private_endpoints(
    client: TestClient, keyed_project: KeyedProject
) -> None:
    response = client.options(
        "/api/v1/emails/send",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in response.headers


def test_docs_can_be_disabled(settings: Settings) -> None:
    from app.main import create_app

    application = create_app(settings.model_copy(update={"DOCS_ENABLED": False}))
    application.dependency_overrides[get_settings] = lambda: settings
    with TestClient(application) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
