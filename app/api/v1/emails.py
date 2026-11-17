from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_project, get_email_service, get_rate_limiter
from app.core.exceptions import NotFoundError
from app.database.session import get_db
from app.models import EmailEvent, EmailLog, Project
from app.schemas.common import ERROR_RESPONSES, Page, SuccessResponse, ok
from app.schemas.email import (
    EmailAccepted,
    EmailEventRead,
    EmailLogDetail,
    EmailLogRead,
    SendEmailRequest,
)
from app.services.email_service import EmailService
from app.services.rate_limiter import RateLimiter

router = APIRouter(prefix="/emails", tags=["emails"], responses=ERROR_RESPONSES)


@router.post(
    "/send",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuccessResponse[EmailAccepted],
)
def send_email(
    body: SendEmailRequest,
    project: Project = Depends(get_current_project),
    email_service: EmailService = Depends(get_email_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> SuccessResponse[EmailAccepted]:
    """Send a transactional email. Requires the project API key, and the
    project must have `transactional_enabled`.

    `202 Accepted` means Resend accepted the request. It is not confirmation
    of inbox delivery. Use `GET /api/v1/emails/{id}` or webhooks for that.
    """
    result = email_service.send_transactional(project, body, limiter)
    return ok(
        "Email accepted for delivery.",
        EmailAccepted(
            id=result.log.id, message_id=result.log.resend_message_id, status=result.log.status
        ),
    )


@router.get("", response_model=SuccessResponse[Page[EmailLogRead]])
def list_emails(
    project: Project = Depends(get_current_project),
    db: Session = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[str | None, Query(alias="status", max_length=32)] = None,
    email_type: Annotated[str | None, Query(max_length=32)] = None,
) -> SuccessResponse[Page[EmailLogRead]]:
    """Email logs of the authenticated project only."""
    return ok(
        "Email logs retrieved.",
        list_email_logs(db, project.id, limit, offset, status_filter, email_type),
    )


@router.get("/{email_id}", response_model=SuccessResponse[EmailLogDetail])
def get_email(
    email_id: uuid.UUID,
    project: Project = Depends(get_current_project),
    db: Session = Depends(get_db),
) -> SuccessResponse[EmailLogDetail]:
    return ok("Email log retrieved.", get_email_log_detail(db, project.id, email_id))


# Shared with the admin router.


def list_email_logs(
    db: Session,
    project_id: uuid.UUID,
    limit: int,
    offset: int,
    status_filter: str | None = None,
    email_type: str | None = None,
) -> Page[EmailLogRead]:
    conditions = [EmailLog.project_id == project_id]
    if status_filter:
        conditions.append(EmailLog.status == status_filter)
    if email_type:
        conditions.append(EmailLog.email_type == email_type)
    total = db.scalar(select(func.count()).select_from(EmailLog).where(*conditions)) or 0
    rows = db.scalars(
        select(EmailLog)
        .where(*conditions)
        .order_by(EmailLog.created_at.desc(), EmailLog.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return Page[EmailLogRead](
        items=[EmailLogRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_email_log_detail(db: Session, project_id: uuid.UUID, email_id: uuid.UUID) -> EmailLogDetail:
    # Filtering by project_id enforces isolation: another project's log is a 404.
    log = db.scalar(
        select(EmailLog).where(EmailLog.id == email_id, EmailLog.project_id == project_id)
    )
    if log is None:
        raise NotFoundError("Email not found.", code="EMAIL_NOT_FOUND")
    events = db.scalars(
        select(EmailEvent).where(EmailEvent.email_log_id == log.id).order_by(EmailEvent.created_at)
    ).all()
    return EmailLogDetail(
        **EmailLogRead.model_validate(log).model_dump(),
        events=[EmailEventRead.model_validate(e) for e in events],
    )
