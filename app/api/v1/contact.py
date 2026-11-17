from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_client_ip,
    get_email_service,
    get_optional_project,
    get_rate_limiter,
)
from app.core.config import Settings, get_settings
from app.database.session import get_db
from app.models import Project
from app.schemas.common import ERROR_RESPONSES, SuccessResponse, ok
from app.schemas.contact import ContactAccepted, ContactRequest
from app.services.contact_service import ContactContext, ContactService
from app.services.email_service import EmailService
from app.services.rate_limiter import RateLimiter
from app.services.turnstile_service import TurnstileVerifier, get_turnstile_verifier

router = APIRouter(tags=["contact"], responses=ERROR_RESPONSES)


@router.post(
    "/contact",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessResponse[ContactAccepted],
)
def submit_contact_form(
    body: ContactRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    email_service: EmailService = Depends(get_email_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
    turnstile: TurnstileVerifier = Depends(get_turnstile_verifier),
    client_ip: str = Depends(get_client_ip),
    api_key_project: Project | None = Depends(get_optional_project),
) -> SuccessResponse[ContactAccepted]:
    """Public contact form endpoint. No private API key is needed in the browser.

    Protected by origin checks, rate limits, a honeypot field (`website`) and
    optional Cloudflare Turnstile. A backend proxy may send the project's API
    key instead, which skips the origin and Turnstile checks.
    """
    service = ContactService(db, settings, email_service, limiter, turnstile)
    outcome = service.submit(
        body,
        ContactContext(
            client_ip=client_ip,
            origin=request.headers.get("origin"),
            authenticated_project=api_key_project,
        ),
    )
    return ok(
        "Your message has been sent.",
        ContactAccepted(id=outcome.submission_id, status=outcome.status),
    )
