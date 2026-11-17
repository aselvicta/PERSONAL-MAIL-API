"""Email dispatch with persistent logging, plus the transactional and
notification use cases.

Every outbound email follows the same sequence:

1. Insert an ``email_logs`` row with status ``pending`` and **commit**, so a
   record exists even if the process dies mid-request.
2. Call Resend. The log id is the idempotency key, so a retried request
   cannot produce a duplicate email.
3. Record the outcome (``accepted`` plus message id, or ``failed`` plus error
   code) and commit.

The sender address is always the project's configured sender or the global
default, never a value supplied by the caller.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import (
    ConfigurationError,
    EmailDeliveryError,
    PermissionDeniedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitExceededError,
)
from app.models import EmailLog, EmailStatus, EmailType, Project
from app.schemas.email import SendEmailRequest
from app.schemas.notification import NotificationRequest
from app.services import template_service
from app.services.project_service import emails_sent_today
from app.services.rate_limiter import RateLimit, RateLimiter
from app.services.resend_service import OutboundEmail, ResendService, SendResult, SendStatus
from app.services.template_service import TemplateName

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EmailContent:
    to: str
    subject: str
    html: str | None = None
    text: str | None = None
    reply_to: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class DispatchResult:
    log: EmailLog
    provider_result: SendResult

    @property
    def accepted(self) -> bool:
        return self.provider_result.accepted


@dataclass(frozen=True, slots=True)
class SenderIdentity:
    email: str
    name: str | None


def resolve_sender(project: Project, settings: Settings) -> SenderIdentity:
    """Return the verified sender identity for a project.

    Callers can never choose an arbitrary From address. It always comes from
    administrator-controlled configuration.
    """
    email = project.sender_email or settings.DEFAULT_FROM_EMAIL
    if not email:
        raise ConfigurationError(
            "No sender address configured. Set DEFAULT_FROM_EMAIL or the project's sender_email.",
            code="SENDER_NOT_CONFIGURED",
        )
    return SenderIdentity(email=email, name=project.sender_name or settings.DEFAULT_FROM_NAME)


def raise_for_failed_dispatch(result: DispatchResult, message: str | None = None) -> None:
    """Translate a failed provider result into the matching API error."""
    if result.accepted:
        return
    provider = result.provider_result
    details = {"id": str(result.log.id), "reason": provider.error_code}
    if provider.status is SendStatus.TIMEOUT:
        raise ProviderTimeoutError(message, details=details)
    if provider.status is SendStatus.UNAVAILABLE:
        raise ProviderUnavailableError(message, details=details, headers={"Retry-After": "30"})
    if provider.status is SendStatus.MISCONFIGURED:
        raise ConfigurationError(message, details=details)
    raise EmailDeliveryError(message or "The email provider rejected the email.", details=details)


_TAG_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def _safe_tags(tags: Mapping[str, str]) -> dict[str, str]:
    # Resend tag names and values allow only ASCII letters, digits, '_' and '-'.
    return {_TAG_UNSAFE.sub("_", k)[:256]: _TAG_UNSAFE.sub("_", v)[:256] for k, v in tags.items()}


class EmailService:
    def __init__(self, db: Session, resend_service: ResendService, settings: Settings) -> None:
        self._db = db
        self._resend = resend_service
        self._settings = settings

    # --- Core dispatch --------------------------------------------------------

    def dispatch(
        self,
        *,
        project: Project,
        email_type: EmailType,
        content: EmailContent,
        sender_name: str | None = None,
        tags: Mapping[str, str] | None = None,
    ) -> DispatchResult:
        sender = resolve_sender(project, self._settings)

        # Build (and validate) the email before writing anything.
        draft = OutboundEmail(
            to=(content.to,),
            subject=content.subject,
            from_email=sender.email,
            from_name=sender_name or sender.name,
            html=content.html,
            text=content.text,
            reply_to=tuple(content.reply_to),
        )

        log = EmailLog(
            project_id=project.id,
            recipient=content.to,
            subject=content.subject[:255],
            email_type=email_type.value,
            status=EmailStatus.PENDING.value,
        )
        self._db.add(log)
        self._db.commit()

        outbound = replace(
            draft,
            idempotency_key=f"email-log/{log.id}",
            tags=_safe_tags(
                {"project": project.slug, "email_type": email_type.value, **(tags or {})}
            ),
        )
        result = self._resend.send(outbound)

        if result.accepted:
            log.status = EmailStatus.ACCEPTED.value
            log.resend_message_id = result.message_id
        else:
            log.status = EmailStatus.FAILED.value
            log.error_code = result.error_code.value if result.error_code else None
            log.error_message = result.error_message
            logger.warning(
                "Email dispatch failed log_id=%s project=%s code=%s",
                log.id,
                project.slug,
                log.error_code,
            )
        self._db.commit()
        return DispatchResult(log=log, provider_result=result)

    # --- Limits ---------------------------------------------------------------

    def enforce_project_limits(
        self, project: Project, limiter: RateLimiter, emails: int = 1
    ) -> None:
        """Per-minute request rate limit and per-day email quota."""
        limiter.hit(RateLimit(f"project:{project.id}:minute", project.rate_limit, 60))
        if emails_sent_today(self._db, project.id) + emails > project.daily_quota:
            raise RateLimitExceededError(
                "The project's daily email quota has been reached.",
                code="DAILY_QUOTA_EXCEEDED",
            )

    # --- Use cases ------------------------------------------------------------

    def send_transactional(
        self, project: Project, request: SendEmailRequest, limiter: RateLimiter
    ) -> DispatchResult:
        if not project.transactional_enabled:
            raise PermissionDeniedError(
                "Transactional email is not enabled for this project.",
                code="TRANSACTIONAL_DISABLED",
            )
        domain = request.to.rsplit("@", 1)[1].lower()
        allowed = {d.lower() for d in project.allowed_recipient_domains}
        if allowed and domain not in allowed:
            raise PermissionDeniedError(
                "This project may not send email to that recipient domain.",
                code="RECIPIENT_NOT_ALLOWED",
            )
        self.enforce_project_limits(project, limiter)

        if request.template:
            variables = dict(request.variables)
            # Sensible defaults so callers only pass what is specific to them.
            variables.setdefault("app_name", project.name)
            if request.template == TemplateName.NOTIFICATION:
                variables.setdefault("project_name", project.name)
            rendered = template_service.render(TemplateName(request.template), variables)
            subject = request.subject or rendered.subject
            html, text = rendered.html, rendered.text
        else:
            assert request.subject is not None  # noqa: S101 (guaranteed by schema)
            subject, html, text = request.subject, request.html, request.text

        result = self.dispatch(
            project=project,
            email_type=EmailType.TRANSACTIONAL,
            content=EmailContent(
                to=request.to,
                subject=subject,
                html=html,
                text=text,
                reply_to=(request.reply_to,) if request.reply_to else (),
            ),
            sender_name=request.sender_name,
            tags={"template": request.template} if request.template else None,
        )
        raise_for_failed_dispatch(result)
        return result

    def send_notification(
        self, project: Project, request: NotificationRequest, limiter: RateLimiter
    ) -> DispatchResult:
        if not project.notifications_enabled:
            raise PermissionDeniedError(
                "Notifications are not enabled for this project.", code="NOTIFICATIONS_DISABLED"
            )
        self.enforce_project_limits(project, limiter)
        rendered = template_service.render(
            TemplateName.NOTIFICATION,
            {
                "project_name": project.name,
                "notification_type": request.type,
                "title": request.subject,
                "message": request.message,
                "details": request.details or None,
            },
        )
        result = self.dispatch(
            project=project,
            email_type=EmailType.NOTIFICATION,
            # Always the administrator-configured recipient.
            content=EmailContent(
                to=project.recipient_email,
                subject=rendered.subject,
                html=rendered.html,
                text=rendered.text,
            ),
            tags={"notification_type": request.type},
        )
        raise_for_failed_dispatch(result)
        return result
