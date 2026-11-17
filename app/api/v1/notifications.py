from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_current_project, get_email_service, get_rate_limiter
from app.models import Project
from app.schemas.common import ERROR_RESPONSES, SuccessResponse, ok
from app.schemas.email import EmailAccepted
from app.schemas.notification import NotificationRequest
from app.services.email_service import EmailService
from app.services.rate_limiter import RateLimiter

router = APIRouter(tags=["notifications"], responses=ERROR_RESPONSES)


@router.post(
    "/notifications",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuccessResponse[EmailAccepted],
)
def send_notification(
    body: NotificationRequest,
    project: Project = Depends(get_current_project),
    email_service: EmailService = Depends(get_email_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> SuccessResponse[EmailAccepted]:
    """Notify the project's configured recipient (new sign-up, enquiry, and so on).

    The recipient is always the administrator-configured `recipient_email`.
    Callers cannot choose it.
    """
    result = email_service.send_notification(project, body, limiter)
    return ok(
        "Notification accepted for delivery.",
        EmailAccepted(
            id=result.log.id, message_id=result.log.resend_message_id, status=result.log.status
        ),
    )
