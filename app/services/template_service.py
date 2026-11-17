"""Email template rendering.

* HTML templates are rendered with Jinja2 **autoescaping**, so untrusted
  variables can never inject markup or scripts.
* Each template declares its required and optional variables. Unknown
  variables are rejected, which catches typos and stops callers from
  smuggling in values.
* URL variables must be absolute ``http(s)`` URLs, so ``javascript:`` links
  are impossible.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.exceptions import AppError
from app.schemas.validators import no_line_breaks

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


class TemplateName(StrEnum):
    CONTACT_NOTIFICATION = "contact_notification"
    CONTACT_ACKNOWLEDGEMENT = "contact_acknowledgement"
    NOTIFICATION = "notification"
    WELCOME = "welcome"
    PASSWORD_RESET = "password_reset"  # noqa: S105
    EMAIL_VERIFICATION = "email_verification"


class TemplateError(AppError):
    code = "INVALID_TEMPLATE_VARIABLES"
    message = "Template variables are invalid."


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    subject: str  # Jinja expression rendered without HTML escaping
    required: frozenset[str]
    optional: frozenset[str] = frozenset()
    url_fields: frozenset[str] = frozenset()
    # Variables that end up in the Subject header.
    header_fields: frozenset[str] = field(default_factory=frozenset)


SPECS: dict[TemplateName, TemplateSpec] = {
    TemplateName.CONTACT_NOTIFICATION: TemplateSpec(
        subject="New message from your {{ project_name }}: {{ subject }}",
        required=frozenset(
            {"project_name", "sender_name", "sender_email", "subject", "message", "submitted_at"}
        ),
        header_fields=frozenset({"project_name", "subject"}),
    ),
    TemplateName.CONTACT_ACKNOWLEDGEMENT: TemplateSpec(
        subject="We received your message - {{ project_name }}",
        required=frozenset({"project_name"}),
        header_fields=frozenset({"project_name"}),
    ),
    TemplateName.NOTIFICATION: TemplateSpec(
        subject="[{{ project_name }}] {{ title }}",
        required=frozenset({"project_name", "notification_type", "title", "message"}),
        optional=frozenset({"details"}),
        header_fields=frozenset({"project_name", "title"}),
    ),
    TemplateName.WELCOME: TemplateSpec(
        subject="Welcome to {{ app_name }}",
        required=frozenset({"app_name"}),
        optional=frozenset({"name", "message", "action_url", "action_text"}),
        url_fields=frozenset({"action_url"}),
        header_fields=frozenset({"app_name"}),
    ),
    TemplateName.PASSWORD_RESET: TemplateSpec(
        subject="Reset your {{ app_name }} password",
        required=frozenset({"app_name", "reset_url"}),
        optional=frozenset({"name", "expires_in_minutes"}),
        url_fields=frozenset({"reset_url"}),
        header_fields=frozenset({"app_name"}),
    ),
    TemplateName.EMAIL_VERIFICATION: TemplateSpec(
        subject="Confirm your email address for {{ app_name }}",
        required=frozenset({"app_name"}),
        optional=frozenset({"name", "verification_url", "code", "expires_in_minutes"}),
        url_fields=frozenset({"verification_url"}),
        header_fields=frozenset({"app_name"}),
    ),
}

# Templates a project may use through POST /api/v1/emails/send.
TRANSACTIONAL_TEMPLATES = frozenset(
    {
        TemplateName.WELCOME,
        TemplateName.PASSWORD_RESET,
        TemplateName.EMAIL_VERIFICATION,
        TemplateName.NOTIFICATION,
    }
)

MAX_VARIABLE_LENGTH = 5000


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    html: str
    text: str


@lru_cache
def _environments() -> tuple[Environment, Environment]:
    loader = FileSystemLoader(TEMPLATE_DIR)
    html_env = Environment(
        loader=loader,
        autoescape=select_autoescape(enabled_extensions=("html",), default=True),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # Plain-text bodies and subjects are not HTML, so they are not escaped.
    text_env = Environment(
        loader=loader,
        autoescape=False,  # noqa: S701 (plain text, never rendered as HTML)
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    return html_env, text_env


def _validate(name: TemplateName, spec: TemplateSpec, variables: Mapping[str, Any]) -> None:
    errors: list[str] = []
    provided = {k for k, v in variables.items() if v not in (None, "")}
    missing = spec.required - provided
    unknown = set(variables) - spec.required - spec.optional - {"app_name"}
    if missing:
        errors.append(f"missing required variables: {', '.join(sorted(missing))}")
    if unknown:
        errors.append(f"unknown variables: {', '.join(sorted(unknown))}")
    for key in spec.url_fields & provided:
        value = str(variables[key])
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            errors.append(f"{key} must be an absolute http(s) URL")
    for key in spec.header_fields & provided:
        try:
            no_line_breaks(str(variables[key]))
        except ValueError:
            errors.append(f"{key} must not contain line breaks")
    for key, value in variables.items():
        if isinstance(value, str) and len(value) > MAX_VARIABLE_LENGTH:
            errors.append(f"{key} exceeds {MAX_VARIABLE_LENGTH} characters")
    if errors:
        raise TemplateError(f"Invalid variables for template '{name}'.", details=errors)


def render(name: TemplateName, variables: Mapping[str, Any]) -> RenderedEmail:
    spec = SPECS[name]
    _validate(name, spec, variables)

    context: dict[str, Any] = {k: None for k in spec.optional}
    context.update(variables)
    context.setdefault("app_name", context.get("project_name"))

    html_env, text_env = _environments()
    subject = text_env.from_string(spec.subject).render(context).strip()
    html = html_env.get_template(f"{name}.html").render(context)
    text = text_env.get_template(f"{name}.txt").render(context).strip() + "\n"
    return RenderedEmail(subject=" ".join(subject.split())[:255], html=html, text=text)
