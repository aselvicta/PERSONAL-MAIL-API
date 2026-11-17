"""Public contact form handling.

The flow for ``POST /api/v1/contact``:

1. Identify the project by its public slug. It must be active and have
   contact enabled.
2. Abuse protection, in order of cost:
   * honeypot field (bots get a fake success and nothing is stored or sent)
   * origin check against the project's ``allowed_origins``
   * per-IP and per-project rate limits, and the daily quota
   * Cloudflare Turnstile, when enabled for the project
   A request carrying the project's own API key (a trusted backend proxy)
   skips the origin and Turnstile checks, but not the limits.
3. Store the submission.
4. Email the administrator-configured recipient, with Reply-To set to the
   submitter.
5. Optionally send the submitter an acknowledgement. It contains no
   submitter-controlled text, so it cannot be used to relay spam.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConfigurationError, NotFoundError, PermissionDeniedError
from app.models import ContactStatus, ContactSubmission, EmailType, Project
from app.schemas.contact import ContactRequest
from app.services import template_service
from app.services.email_service import EmailContent, EmailService, raise_for_failed_dispatch
from app.services.rate_limiter import RateLimit, RateLimiter
from app.services.template_service import TemplateName
from app.services.turnstile_service import TurnstileVerifier

logger = logging.getLogger(__name__)

HONEYPOT_ID = uuid.UUID(int=0)


@dataclass(frozen=True, slots=True)
class ContactContext:
    client_ip: str
    origin: str | None
    authenticated_project: Project | None  # set when a valid API key was presented


@dataclass(frozen=True, slots=True)
class ContactOutcome:
    submission_id: uuid.UUID
    status: str


class ContactService:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        email_service: EmailService,
        limiter: RateLimiter,
        turnstile: TurnstileVerifier,
    ) -> None:
        self._db = db
        self._settings = settings
        self._email = email_service
        self._limiter = limiter
        self._turnstile = turnstile

    def submit(self, request: ContactRequest, ctx: ContactContext) -> ContactOutcome:
        project = self._load_project(request.project)

        if ctx.authenticated_project is not None and ctx.authenticated_project.id != project.id:
            raise PermissionDeniedError(
                "This API key does not belong to the requested project.", code="PROJECT_MISMATCH"
            )
        trusted = ctx.authenticated_project is not None

        if request.website:
            logger.info("Contact honeypot triggered for project=%s", project.slug)
            return ContactOutcome(submission_id=HONEYPOT_ID, status=ContactStatus.SENT.value)

        if not trusted:
            self._check_origin(project, ctx.origin)

        self._limiter.hit(
            RateLimit(
                f"contact:{project.id}:ip:{ctx.client_ip}",
                self._settings.CONTACT_RATE_LIMIT_PER_IP,
                3600,
            )
        )
        emails = 2 if project.acknowledgement_enabled else 1
        self._email.enforce_project_limits(project, self._limiter, emails=emails)

        if not trusted and project.turnstile_enabled:
            self._check_turnstile(request.turnstile_token, ctx.client_ip)

        submission = ContactSubmission(
            project_id=project.id,
            sender_name=request.name.strip(),
            sender_email=request.email,
            subject=request.subject.strip(),
            message=request.message.strip(),
            status=ContactStatus.RECEIVED.value,
        )
        self._db.add(submission)
        self._db.commit()

        rendered = template_service.render(
            TemplateName.CONTACT_NOTIFICATION,
            {
                "project_name": project.name,
                "sender_name": submission.sender_name,
                "sender_email": submission.sender_email,
                "subject": submission.subject,
                "message": submission.message,
                "submitted_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            },
        )
        result = self._email.dispatch(
            project=project,
            email_type=EmailType.CONTACT_NOTIFICATION,
            content=EmailContent(
                to=project.recipient_email,
                subject=rendered.subject,
                html=rendered.html,
                text=rendered.text,
                reply_to=(submission.sender_email,),
            ),
        )
        submission.status = (
            ContactStatus.SENT.value if result.accepted else ContactStatus.FAILED.value
        )
        submission.resend_message_id = result.provider_result.message_id
        self._db.commit()
        raise_for_failed_dispatch(
            result,
            "Your message was saved but could not be delivered right now.",
        )

        if project.acknowledgement_enabled:
            self._send_acknowledgement(project, submission)

        return ContactOutcome(submission_id=submission.id, status=submission.status)

    # --- helpers --------------------------------------------------------------

    def _load_project(self, slug: str) -> Project:
        project = self._db.scalar(select(Project).where(Project.slug == slug))
        # Same response for unknown, inactive and contact-disabled projects, so
        # the endpoint cannot be used to enumerate projects.
        if project is None or not project.is_active or not project.contact_enabled:
            raise NotFoundError("Project not found.", code="PROJECT_NOT_FOUND")
        return project

    @staticmethod
    def _check_origin(project: Project, origin: str | None) -> None:
        allowed = {o.lower() for o in project.allowed_origins}
        if not allowed:
            return
        if not origin or origin.rstrip("/").lower() not in allowed:
            raise PermissionDeniedError(
                "Requests from this origin are not allowed.", code="ORIGIN_NOT_ALLOWED"
            )

    def _check_turnstile(self, token: str | None, client_ip: str) -> None:
        if not self._turnstile.configured:
            raise ConfigurationError(
                "Turnstile is enabled for this project but TURNSTILE_SECRET_KEY is not set.",
                code="TURNSTILE_NOT_CONFIGURED",
            )
        if not token or not self._turnstile.verify(token, client_ip):
            raise PermissionDeniedError(
                "Spam protection check failed. Please try again.", code="TURNSTILE_FAILED"
            )

    def _send_acknowledgement(self, project: Project, submission: ContactSubmission) -> None:
        rendered = template_service.render(
            TemplateName.CONTACT_ACKNOWLEDGEMENT, {"project_name": project.name}
        )
        result = self._email.dispatch(
            project=project,
            email_type=EmailType.CONTACT_ACKNOWLEDGEMENT,
            content=EmailContent(
                to=submission.sender_email,
                subject=rendered.subject,
                html=rendered.html,
                text=rendered.text,
                reply_to=(project.recipient_email,),
            ),
        )
        if not result.accepted:
            # The owner already has the message. A failed courtesy reply is
            # logged but does not fail the request.
            logger.warning("Contact acknowledgement failed for project=%s", project.slug)
