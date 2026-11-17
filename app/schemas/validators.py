"""Reusable field types and validators."""

from __future__ import annotations

import re
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator, EmailStr, StringConstraints

_LINE_BREAKS = re.compile(r"[\r\n\u2028\u2029]")
_DOMAIN = re.compile(r"^(?=.{1,253}$)(?!-)([a-z0-9-]{1,63}(?<!-)\.)+[a-z]{2,63}$")
_SLUG = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


def no_line_breaks(value: str) -> str:
    """Reject values that would end up in an email header with CR/LF."""
    if _LINE_BREAKS.search(value):
        raise ValueError("must not contain line breaks")
    return value


def normalize_email(value: str) -> str:
    local, _, domain = value.rpartition("@")
    return f"{local}@{domain.lower()}"


def normalize_origin(value: str) -> str:
    value = value.strip().rstrip("/").lower()
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("origin must look like https://example.com")
    if parts.path or parts.query or parts.fragment or parts.username:
        raise ValueError("origin must not include a path, query or credentials")
    try:
        parts.port  # noqa: B018  # raises ValueError for a malformed port
    except ValueError:
        raise ValueError("origin has an invalid port") from None
    if value.endswith(":"):
        raise ValueError("origin has an invalid port")
    return value


def normalize_domain(value: str) -> str:
    value = value.strip().lower().lstrip("@")
    if not _DOMAIN.match(value):
        raise ValueError(f"{value!r} is not a valid domain")
    return value


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


HeaderSafeStr = Annotated[str, AfterValidator(no_line_breaks)]
Email = Annotated[EmailStr, AfterValidator(normalize_email)]
Slug = Annotated[str, StringConstraints(min_length=2, max_length=64, pattern=_SLUG)]
Origin = Annotated[str, AfterValidator(normalize_origin)]
Domain = Annotated[str, AfterValidator(normalize_domain)]
OriginList = Annotated[list[Origin], AfterValidator(_unique)]
DomainList = Annotated[list[Domain], AfterValidator(_unique)]
