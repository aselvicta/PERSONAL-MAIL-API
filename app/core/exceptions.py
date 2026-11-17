"""Application exceptions and the handlers that render them as JSON envelopes.

Every error response has the shape::

    {"success": false, "message": "...", "error": {"code": "...", "details": ...}}

Internal exception text and stack traces are never returned to clients.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for errors that map to a well-defined API response."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"
    message: str = "The request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details
        self.headers = headers
        super().__init__(self.message)


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHORIZED"
    message = "Authentication is required."


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"
    message = "You do not have permission to perform this action."


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    message = "The requested resource was not found."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"
    message = "The request conflicts with the current state of the resource."


class RateLimitExceededError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMIT_EXCEEDED"
    message = "Too many requests. Please try again later."


class ConfigurationError(AppError):
    """Server-side misconfiguration, such as a missing sender address."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "SERVICE_MISCONFIGURED"
    message = "The email service is not configured correctly."


class EmailDeliveryError(AppError):
    """The provider rejected the email or could not be reached."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "EMAIL_DELIVERY_FAILED"
    message = "Unable to process email request."


class ProviderTimeoutError(AppError):
    """No answer from the provider in time: the email may or may not be sent."""

    status_code = status.HTTP_504_GATEWAY_TIMEOUT
    code = "EMAIL_PROVIDER_TIMEOUT"
    message = "The email provider did not respond in time. Delivery status is unknown."


class ProviderUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "EMAIL_PROVIDER_UNAVAILABLE"
    message = "The email provider is temporarily unavailable. Please retry later."


def _envelope(message: str, code: str, details: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code}
    if details is not None:
        error["details"] = details
    return {"success": False, "message": message, "error": error}


async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(_envelope(exc.message, exc.code, exc.details)),
        headers=exc.headers,
    )


async def _validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Report where and why validation failed, but never echo the submitted
    # input back: it may be large or contain sensitive data.
    details = [
        {"field": ".".join(str(p) for p in err.get("loc", ())), "message": err.get("msg", "")}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=_envelope("Request validation failed.", "VALIDATION_ERROR", details),
    )


_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    429: "RATE_LIMIT_EXCEEDED",
}


async def _http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(message, code),
        headers=getattr(exc, "headers", None),
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_envelope("An unexpected error occurred.", "INTERNAL_SERVER_ERROR"),
    )


def register_exception_handlers(app: FastAPI) -> None:
    # Starlette's stub types handlers as taking ``Exception``; it dispatches by class.
    app.add_exception_handler(AppError, _app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_exception_handler)
