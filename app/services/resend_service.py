"""Resend integration. This is the only module that talks to the Resend SDK.

``ResendService.send`` never raises for provider problems. It always returns a
``SendResult``, so callers can record the outcome and decide how to respond.

* ``ACCEPTED`` means Resend accepted the API request and returned a message id.
  This is **not** confirmation of inbox delivery; that comes later through webhooks.
* ``REJECTED`` means Resend refused the request (4xx: invalid sender,
  unverified domain, validation error). Retrying will not help.
* ``TIMEOUT`` means no answer within ``RESEND_TIMEOUT_SECONDS``. The email may
  or may not have been accepted. Retrying with the same idempotency key is safe.
* ``UNAVAILABLE`` means a network failure, a Resend 5xx or Resend rate limiting.
  Retryable.
* ``MISCONFIGURED`` means the API key is missing or invalid. Operator action
  is required.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from typing import Any

import requests
import resend
from resend.exceptions import ResendError
from resend.http_client_requests import RequestsClient

from app.core.config import get_settings
from app.core.logging import redact

logger = logging.getLogger(__name__)

_LINE_BREAK = re.compile(r"[\r\n]")
_UNSAFE_DISPLAY_NAME_CHARS = re.compile(r'[\r\n"<>\\]')


class SendStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    MISCONFIGURED = "misconfigured"


class ProviderErrorCode(StrEnum):
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    PROVIDER_AUTH_FAILED = "PROVIDER_AUTH_FAILED"
    PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"


@dataclass(frozen=True, slots=True)
class SendResult:
    status: SendStatus
    message_id: str | None = None
    error_code: ProviderErrorCode | None = None
    error_message: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status is SendStatus.ACCEPTED

    @property
    def retryable(self) -> bool:
        return self.status in {SendStatus.TIMEOUT, SendStatus.UNAVAILABLE}


@dataclass(frozen=True, slots=True)
class OutboundEmail:
    """A fully resolved email, ready to hand to Resend.

    Header-bearing fields are checked for CR/LF to prevent header injection.
    Address syntax is validated at the API boundary by Pydantic.
    """

    to: Sequence[str]
    subject: str
    from_email: str
    from_name: str | None = None
    html: str | None = None
    text: str | None = None
    reply_to: Sequence[str] = field(default_factory=tuple)
    idempotency_key: str | None = None
    tags: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.to:
            raise ValueError("at least one recipient is required")
        if not (self.html or self.text):
            raise ValueError("an HTML or plain-text body is required")
        header_values = [self.subject, self.from_email, *self.to, *self.reply_to]
        if self.from_name:
            header_values.append(self.from_name)
        if any(_LINE_BREAK.search(v) for v in header_values):
            raise ValueError("header values must not contain line breaks")

    @property
    def formatted_from(self) -> str:
        if not self.from_name:
            return self.from_email
        name = _UNSAFE_DISPLAY_NAME_CHARS.sub("", self.from_name).strip()
        return f'"{name}" <{self.from_email}>' if name else self.from_email


class _ProviderTimeout(Exception):
    """Raised by our HTTP client so timeouts can be told apart from other failures."""


class _TimeoutAwareRequestsClient(RequestsClient):
    """The SDK's requests client, with a configurable timeout and a distinct
    timeout signal.

    The SDK wraps every transport exception in a generic ``ResendError``. We
    raise ``_ProviderTimeout`` here and find it again on the exception chain.
    """

    def __init__(self, timeout: float) -> None:
        super().__init__(timeout=timeout)  # type: ignore[arg-type]

    def request(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return super().request(*args, **kwargs)
        except RuntimeError as exc:
            if isinstance(exc.__cause__, requests.Timeout):
                raise _ProviderTimeout(str(exc.__cause__)) from exc
            raise


def _chain_contains_timeout(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, (_ProviderTimeout, requests.Timeout)):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def _to_int(code: object) -> int | None:
    try:
        return int(code)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None


class ResendService:
    """Thin, exception-safe wrapper around ``resend.Emails.send``.

    The Resend SDK keeps its API key and HTTP client as module-level globals,
    so the application uses a single instance (see ``get_resend_service``).
    """

    def __init__(self, api_key: str | None, timeout_seconds: float) -> None:
        self._configured = bool(api_key)
        resend.api_key = api_key
        resend.default_http_client = _TimeoutAwareRequestsClient(timeout_seconds)

    @property
    def configured(self) -> bool:
        return self._configured

    def send(self, email: OutboundEmail) -> SendResult:
        if not self._configured:
            return SendResult(
                status=SendStatus.MISCONFIGURED,
                error_code=ProviderErrorCode.PROVIDER_NOT_CONFIGURED,
                error_message="RESEND_API_KEY is not configured.",
            )

        params: dict[str, Any] = {
            "from": email.formatted_from,
            "to": list(email.to),
            "subject": email.subject,
        }
        if email.html:
            params["html"] = email.html
        if email.text:
            params["text"] = email.text
        if email.reply_to:
            params["reply_to"] = list(email.reply_to)
        if email.tags:
            params["tags"] = [{"name": k, "value": v} for k, v in email.tags.items()]

        options: dict[str, Any] = {}
        if email.idempotency_key:
            options["idempotency_key"] = email.idempotency_key

        try:
            response = resend.Emails.send(params, options or None)  # type: ignore[arg-type]
        except ResendError as exc:
            return self._result_from_error(exc)
        except Exception as exc:  # Defensive: never let SDK internals escape.
            if _chain_contains_timeout(exc):
                return self._timeout_result()
            logger.exception("Unexpected error while calling Resend")
            return SendResult(
                status=SendStatus.UNAVAILABLE,
                error_code=ProviderErrorCode.PROVIDER_UNAVAILABLE,
                error_message="Unexpected error while contacting the email provider.",
            )

        message_id = response.get("id") if isinstance(response, Mapping) else None
        if not message_id:
            logger.error("Resend response did not include a message id")
            return SendResult(
                status=SendStatus.UNAVAILABLE,
                error_code=ProviderErrorCode.PROVIDER_UNAVAILABLE,
                error_message="Email provider returned an unexpected response.",
            )
        logger.info("Resend accepted email message_id=%s", message_id)
        return SendResult(status=SendStatus.ACCEPTED, message_id=str(message_id))

    @staticmethod
    def _timeout_result() -> SendResult:
        logger.warning("Resend request timed out")
        return SendResult(
            status=SendStatus.TIMEOUT,
            error_code=ProviderErrorCode.PROVIDER_TIMEOUT,
            error_message="Timed out waiting for the email provider.",
        )

    def _result_from_error(self, exc: ResendError) -> SendResult:
        if _chain_contains_timeout(exc):
            return self._timeout_result()

        code = _to_int(exc.code)
        message = redact(str(exc.message or exc))[:1000]

        if exc.error_type == "HttpClientError":
            logger.warning("Could not reach Resend: %s", message)
            return SendResult(
                status=SendStatus.UNAVAILABLE,
                error_code=ProviderErrorCode.PROVIDER_UNAVAILABLE,
                error_message="Could not reach the email provider.",
            )
        if code in (401, 403) and exc.error_type in {
            "missing_api_key",
            "invalid_api_key",
            "restricted_api_key",
        }:
            logger.error("Resend rejected the API key (%s)", exc.error_type)
            return SendResult(
                status=SendStatus.MISCONFIGURED,
                error_code=ProviderErrorCode.PROVIDER_AUTH_FAILED,
                error_message="Email provider rejected the configured credentials.",
            )
        if code == 429:
            logger.warning("Resend rate limit reached: %s", message)
            return SendResult(
                status=SendStatus.UNAVAILABLE,
                error_code=ProviderErrorCode.PROVIDER_RATE_LIMITED,
                error_message=message,
            )
        if code is not None and 400 <= code < 500:
            # e.g. unverified sending domain, invalid recipient, validation_error
            logger.warning("Resend rejected email (%s, %s): %s", code, exc.error_type, message)
            return SendResult(
                status=SendStatus.REJECTED,
                error_code=ProviderErrorCode.PROVIDER_REJECTED,
                error_message=message,
            )
        logger.error("Resend server error (%s): %s", code, message)
        return SendResult(
            status=SendStatus.UNAVAILABLE,
            error_code=ProviderErrorCode.PROVIDER_UNAVAILABLE,
            error_message=message,
        )


@lru_cache
def get_resend_service() -> ResendService:
    settings = get_settings()
    api_key = settings.RESEND_API_KEY.get_secret_value() if settings.RESEND_API_KEY else None
    return ResendService(api_key=api_key, timeout_seconds=settings.RESEND_TIMEOUT_SECONDS)
