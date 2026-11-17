"""Administrator endpoints for managing projects and their API keys."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin, get_project_service
from app.api.v1.emails import get_email_log_detail, list_email_logs
from app.database.session import get_db
from app.models import ContactSubmission
from app.schemas.common import ERROR_RESPONSES, Page, SuccessResponse, ok
from app.schemas.contact import ContactSubmissionRead
from app.schemas.email import EmailLogDetail, EmailLogRead
from app.schemas.project import (
    ApiKeyCreated,
    ApiKeyRead,
    ProjectCreate,
    ProjectCreated,
    ProjectRead,
    ProjectUpdate,
    ProjectUsage,
)
from app.services.project_service import IssuedKey, ProjectService

router = APIRouter(
    prefix="/admin/projects",
    tags=["admin: projects"],
    dependencies=[Depends(get_current_admin)],
    responses=ERROR_RESPONSES,
)

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


def _key_created(issued: IssuedKey) -> ApiKeyCreated:
    return ApiKeyCreated(
        **ApiKeyRead.model_validate(issued.record).model_dump(), api_key=issued.plaintext
    )


@router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=SuccessResponse[ProjectCreated]
)
def create_project(
    body: ProjectCreate, service: ProjectService = Depends(get_project_service)
) -> SuccessResponse[ProjectCreated]:
    """Register a project. The response contains its API key, **shown only once**."""
    project, issued = service.create(body)
    return ok(
        "Project created. Store the API key now; it will not be shown again.",
        ProjectCreated(project=ProjectRead.model_validate(project), api_key=_key_created(issued)),
    )


@router.get("", response_model=SuccessResponse[Page[ProjectRead]])
def list_projects(
    limit: Limit = 50,
    offset: Offset = 0,
    service: ProjectService = Depends(get_project_service),
) -> SuccessResponse[Page[ProjectRead]]:
    items, total = service.list(limit=limit, offset=offset)
    return ok(
        "Projects retrieved.",
        Page[ProjectRead](
            items=[ProjectRead.model_validate(p) for p in items],
            total=total,
            limit=limit,
            offset=offset,
        ),
    )


@router.get("/{project_id}", response_model=SuccessResponse[ProjectRead])
def get_project(
    project_id: uuid.UUID, service: ProjectService = Depends(get_project_service)
) -> SuccessResponse[ProjectRead]:
    return ok("Project retrieved.", ProjectRead.model_validate(service.get(project_id)))


@router.patch("/{project_id}", response_model=SuccessResponse[ProjectRead])
def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    service: ProjectService = Depends(get_project_service),
) -> SuccessResponse[ProjectRead]:
    """Partially update a project's configuration."""
    return ok("Project updated.", ProjectRead.model_validate(service.update(project_id, body)))


@router.delete("/{project_id}", response_model=SuccessResponse[None])
def delete_project(
    project_id: uuid.UUID, service: ProjectService = Depends(get_project_service)
) -> SuccessResponse[None]:
    """Permanently delete a project with its keys, submissions and email logs."""
    service.delete(project_id)
    return ok("Project deleted.")


@router.post("/{project_id}/disable", response_model=SuccessResponse[ProjectRead])
def disable_project(
    project_id: uuid.UUID, service: ProjectService = Depends(get_project_service)
) -> SuccessResponse[ProjectRead]:
    return ok(
        "Project disabled.", ProjectRead.model_validate(service.set_active(project_id, False))
    )


@router.post("/{project_id}/enable", response_model=SuccessResponse[ProjectRead])
def enable_project(
    project_id: uuid.UUID, service: ProjectService = Depends(get_project_service)
) -> SuccessResponse[ProjectRead]:
    return ok("Project enabled.", ProjectRead.model_validate(service.set_active(project_id, True)))


@router.get("/{project_id}/usage", response_model=SuccessResponse[ProjectUsage])
def project_usage(
    project_id: uuid.UUID, service: ProjectService = Depends(get_project_service)
) -> SuccessResponse[ProjectUsage]:
    return ok("Project usage retrieved.", service.usage(project_id))


# --- API keys -----------------------------------------------------------------


@router.get("/{project_id}/api-keys", response_model=SuccessResponse[list[ApiKeyRead]])
def list_api_keys(
    project_id: uuid.UUID, service: ProjectService = Depends(get_project_service)
) -> SuccessResponse[list[ApiKeyRead]]:
    keys = service.list_keys(project_id)
    return ok("API keys retrieved.", [ApiKeyRead.model_validate(k) for k in keys])


@router.post(
    "/{project_id}/api-keys",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessResponse[ApiKeyCreated],
)
def regenerate_api_key(
    project_id: uuid.UUID, service: ProjectService = Depends(get_project_service)
) -> SuccessResponse[ApiKeyCreated]:
    """Revoke all active keys of the project and issue a new one (shown once)."""
    issued = service.regenerate_key(project_id)
    return ok(
        "API key regenerated. Previous keys are revoked. Store the new key now.",
        _key_created(issued),
    )


@router.delete("/{project_id}/api-keys/{key_id}", response_model=SuccessResponse[ApiKeyRead])
def revoke_api_key(
    project_id: uuid.UUID,
    key_id: uuid.UUID,
    service: ProjectService = Depends(get_project_service),
) -> SuccessResponse[ApiKeyRead]:
    return ok("API key revoked.", ApiKeyRead.model_validate(service.revoke_key(project_id, key_id)))


# --- Logs ---------------------------------------------------------------------


@router.get("/{project_id}/emails", response_model=SuccessResponse[Page[EmailLogRead]])
def project_email_logs(
    project_id: uuid.UUID,
    limit: Limit = 20,
    offset: Offset = 0,
    status_filter: Annotated[str | None, Query(alias="status", max_length=32)] = None,
    email_type: Annotated[str | None, Query(max_length=32)] = None,
    db: Session = Depends(get_db),
    service: ProjectService = Depends(get_project_service),
) -> SuccessResponse[Page[EmailLogRead]]:
    service.get(project_id)
    return ok(
        "Email logs retrieved.",
        list_email_logs(db, project_id, limit, offset, status_filter, email_type),
    )


@router.get("/{project_id}/emails/{email_id}", response_model=SuccessResponse[EmailLogDetail])
def project_email_log(
    project_id: uuid.UUID, email_id: uuid.UUID, db: Session = Depends(get_db)
) -> SuccessResponse[EmailLogDetail]:
    return ok("Email log retrieved.", get_email_log_detail(db, project_id, email_id))


@router.get(
    "/{project_id}/contact-submissions",
    response_model=SuccessResponse[Page[ContactSubmissionRead]],
)
def project_contact_submissions(
    project_id: uuid.UUID,
    limit: Limit = 20,
    offset: Offset = 0,
    db: Session = Depends(get_db),
    service: ProjectService = Depends(get_project_service),
) -> SuccessResponse[Page[ContactSubmissionRead]]:
    service.get(project_id)
    condition = ContactSubmission.project_id == project_id
    total = db.scalar(select(func.count()).select_from(ContactSubmission).where(condition)) or 0
    rows = db.scalars(
        select(ContactSubmission)
        .where(condition)
        .order_by(ContactSubmission.created_at.desc(), ContactSubmission.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return ok(
        "Contact submissions retrieved.",
        Page[ContactSubmissionRead](
            items=[ContactSubmissionRead.model_validate(r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
        ),
    )
