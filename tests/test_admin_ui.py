"""The built-in admin web page at /admin."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.schemas.validators import normalize_origin


def test_root_redirects_to_admin(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/admin"


def test_admin_page_is_served_with_strict_csp(client: TestClient) -> None:
    response = client.get("/admin")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Sign in" in response.text
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp
    assert response.headers["x-frame-options"] == "DENY"


def test_admin_assets_are_served(client: TestClient) -> None:
    js = client.get("/admin/assets/admin.js")
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]
    assert "content-security-policy" in js.headers
    assert client.get("/admin/assets/admin.css").status_code == 200
    assert client.get("/admin/assets/missing.js").status_code == 404


def test_admin_js_never_uses_inner_html(client: TestClient) -> None:
    # Server values are rendered with textContent only.
    assert "innerHTML" not in client.get("/admin/assets/admin.js").text


def test_api_responses_have_no_admin_csp(client: TestClient) -> None:
    assert "content-security-policy" not in client.get("/health").headers


def test_admin_page_does_not_bypass_api_auth(client: TestClient) -> None:
    # The page is public; the data behind it is not.
    assert client.get("/api/v1/admin/projects").status_code == 401


def test_admin_ui_can_be_disabled(settings: Settings) -> None:
    from app.main import create_app

    application = create_app(settings.model_copy(update={"ADMIN_UI_ENABLED": False}))
    application.dependency_overrides[get_settings] = lambda: settings
    with TestClient(application) as client:
        assert client.get("/admin").status_code == 404
        assert client.get("/admin/assets/admin.js").status_code == 404


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://Victor.vercel.app/", "https://victor.vercel.app"),
        ("http://localhost:3000", "http://localhost:3000"),
    ],
)
def test_origin_normalization(raw: str, expected: str) -> None:
    assert normalize_origin(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "ftp://files.example.com",
        "victor.vercel.app",
        "https://site.com/contact",
        "https://javascript:alert(1)",
        "https://site.com:99999",
        "https://site.com:",
        "https://user@site.com",
    ],
)
def test_invalid_origins_are_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_origin(raw)
