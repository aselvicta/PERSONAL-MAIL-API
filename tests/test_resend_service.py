"""ResendService tests.

These run the real Resend SDK request path and stub only the HTTP transport
(``requests.request``), so they check how genuine SDK responses are
classified. No network traffic is generated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest
import requests

from app.services.resend_service import (
    OutboundEmail,
    ProviderErrorCode,
    ResendService,
    SendStatus,
)


@dataclass
class FakeHTTPResponse:
    status_code: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=lambda: {"content-type": "application/json"})

    @property
    def content(self) -> bytes:
        return json.dumps(self.body).encode()


@dataclass
class Transport:
    response: FakeHTTPResponse | None = None
    error: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, **kwargs: Any) -> FakeHTTPResponse:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        assert self.response is not None
        return self.response


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> Transport:
    fake = Transport()
    monkeypatch.setattr(requests, "request", fake)
    return fake


@pytest.fixture
def service() -> ResendService:
    return ResendService(api_key="re_test_placeholder_key", timeout_seconds=3)


def email(**overrides: Any) -> OutboundEmail:
    values: dict[str, Any] = {
        "to": ["user@example.com"],
        "subject": "Welcome",
        "from_email": "noreply@mail.example.com",
        "from_name": "CareerDocs",
        "html": "<p>Hello</p>",
        "text": "Hello",
        "reply_to": ["support@example.com"],
        "idempotency_key": "email-log/abc",
        "tags": {"project": "careerdocs"},
    }
    values.update(overrides)
    return OutboundEmail(**values)


def test_accepted_email_returns_message_id(service: ResendService, transport: Transport) -> None:
    transport.response = FakeHTTPResponse(200, {"id": "4ef9a417-02e9-4d39-ad75-9611e0fcc33c"})

    result = service.send(email())

    assert result.status is SendStatus.ACCEPTED
    assert result.accepted
    assert result.message_id == "4ef9a417-02e9-4d39-ad75-9611e0fcc33c"

    (call,) = transport.calls
    assert call["url"].endswith("/emails")
    assert call["timeout"] == 3
    assert call["headers"]["Idempotency-Key"] == "email-log/abc"
    payload = call["json"]
    assert payload["from"] == '"CareerDocs" <noreply@mail.example.com>'
    assert payload["to"] == ["user@example.com"]
    assert payload["reply_to"] == ["support@example.com"]
    assert payload["html"] == "<p>Hello</p>"
    assert payload["text"] == "Hello"
    assert payload["tags"] == [{"name": "project", "value": "careerdocs"}]


def test_validation_error_is_a_rejection(service: ResendService, transport: Transport) -> None:
    transport.response = FakeHTTPResponse(
        422, {"statusCode": 422, "name": "validation_error", "message": "Invalid `to` field."}
    )

    result = service.send(email())

    assert result.status is SendStatus.REJECTED
    assert result.error_code is ProviderErrorCode.PROVIDER_REJECTED
    assert result.error_message == "Invalid `to` field."
    assert not result.retryable


def test_unverified_domain_is_a_rejection_not_an_auth_failure(
    service: ResendService, transport: Transport
) -> None:
    transport.response = FakeHTTPResponse(
        403,
        {
            "statusCode": 403,
            "name": "validation_error",
            "message": "The mail.example.com domain is not verified.",
        },
    )
    result = service.send(email())
    assert result.status is SendStatus.REJECTED
    assert result.error_code is ProviderErrorCode.PROVIDER_REJECTED


def test_invalid_api_key_is_a_misconfiguration(
    service: ResendService, transport: Transport
) -> None:
    transport.response = FakeHTTPResponse(
        403, {"statusCode": 403, "name": "invalid_api_key", "message": "API key is invalid"}
    )
    result = service.send(email())
    assert result.status is SendStatus.MISCONFIGURED
    assert result.error_code is ProviderErrorCode.PROVIDER_AUTH_FAILED


def test_provider_rate_limit_is_retryable(service: ResendService, transport: Transport) -> None:
    transport.response = FakeHTTPResponse(
        429, {"statusCode": 429, "name": "rate_limit_exceeded", "message": "Too many requests"}
    )
    result = service.send(email())
    assert result.status is SendStatus.UNAVAILABLE
    assert result.error_code is ProviderErrorCode.PROVIDER_RATE_LIMITED
    assert result.retryable


def test_provider_server_error_is_unavailable(service: ResendService, transport: Transport) -> None:
    transport.response = FakeHTTPResponse(
        500, {"statusCode": 500, "name": "application_error", "message": "Internal error"}
    )
    result = service.send(email())
    assert result.status is SendStatus.UNAVAILABLE
    assert result.error_code is ProviderErrorCode.PROVIDER_UNAVAILABLE


def test_non_json_gateway_error_is_unavailable(
    service: ResendService, transport: Transport
) -> None:
    transport.response = FakeHTTPResponse(502, {}, headers={"content-type": "text/html"})
    result = service.send(email())
    assert result.status is SendStatus.UNAVAILABLE


def test_timeout_is_distinguished(service: ResendService, transport: Transport) -> None:
    transport.error = requests.ReadTimeout("read timed out")

    result = service.send(email())

    assert result.status is SendStatus.TIMEOUT
    assert result.error_code is ProviderErrorCode.PROVIDER_TIMEOUT
    assert result.retryable


def test_connection_error_is_unavailable(service: ResendService, transport: Transport) -> None:
    transport.error = requests.ConnectionError("connection refused")
    result = service.send(email())
    assert result.status is SendStatus.UNAVAILABLE
    assert result.error_code is ProviderErrorCode.PROVIDER_UNAVAILABLE


def test_missing_api_key_never_calls_provider(transport: Transport) -> None:
    service = ResendService(api_key=None, timeout_seconds=3)
    result = service.send(email())
    assert result.status is SendStatus.MISCONFIGURED
    assert result.error_code is ProviderErrorCode.PROVIDER_NOT_CONFIGURED
    assert transport.calls == []


def test_response_without_id_is_not_treated_as_accepted(
    service: ResendService, transport: Transport
) -> None:
    transport.response = FakeHTTPResponse(200, {})
    result = service.send(email())
    assert result.status is SendStatus.UNAVAILABLE


def test_error_messages_never_contain_api_key(service: ResendService, transport: Transport) -> None:
    transport.response = FakeHTTPResponse(
        422,
        {
            "statusCode": 422,
            "name": "validation_error",
            "message": "bad key re_test_placeholder_key",
        },
    )
    result = service.send(email())
    assert result.error_message is not None
    assert "re_test_placeholder_key" not in result.error_message


@pytest.mark.parametrize(
    "overrides",
    [
        {"subject": "Hi\r\nBcc: victim@example.com"},
        {"from_name": "Name\nBcc: victim@example.com"},
        {"to": ["user@example.com\r\nBcc: victim@example.com"]},
        {"reply_to": ["a@example.com\nX: y"]},
    ],
)
def test_header_injection_is_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="line breaks"):
        email(**overrides)


def test_email_requires_a_body_and_recipient() -> None:
    with pytest.raises(ValueError, match="body"):
        email(html=None, text=None)
    with pytest.raises(ValueError, match="recipient"):
        email(to=[])


def test_display_name_is_quoted_and_sanitised() -> None:
    assert (
        email(from_name='Evil "<attacker@x.com>"').formatted_from
        == '"Evil attacker@x.com" <noreply@mail.example.com>'
    )
    assert email(from_name=None).formatted_from == "noreply@mail.example.com"
