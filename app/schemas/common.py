"""Standard response envelopes shared by every endpoint."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SuccessResponse[T](BaseModel):
    success: bool = True
    message: str
    data: T | None = None


class ErrorBody(BaseModel):
    code: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    success: bool = False
    message: str
    error: ErrorBody


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


def ok[T](message: str, data: T | None = None) -> SuccessResponse[T]:
    return SuccessResponse[T](message=message, data=data)


# Documented on every endpoint that can fail with an envelope.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 409, 413, 422, 429, 502, 503)
}
