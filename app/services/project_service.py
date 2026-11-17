"""Project administration and API key lifecycle."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.core.security import generate_api_key, hash_api_key, looks_like_api_key
from app.models import ApiKey, ContactSubmission, EmailLog, Project
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectUsage


class SenderDomainNotAllowedError(AppError):
    code = "SENDER_DOMAIN_NOT_ALLOWED"


@dataclass(frozen=True, slots=True)
class IssuedKey:
    record: ApiKey
    plaintext: str


def start_of_utc_day(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return datetime.combine(now.date(), time.min, tzinfo=UTC)


class ProjectService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    # --- Projects -----------------------------------------------------------

    def create(self, data: ProjectCreate) -> tuple[Project, IssuedKey]:
        self._check_sender_domain(data.sender_email)
        if self._db.scalar(select(Project.id).where(Project.slug == data.slug)):
            raise ConflictError(
                f"A project with slug '{data.slug}' already exists.", code="PROJECT_SLUG_TAKEN"
            )
        project = Project(**data.model_dump())
        self._db.add(project)
        try:
            self._db.flush()
        except IntegrityError as exc:  # concurrent create with the same slug
            self._db.rollback()
            raise ConflictError(code="PROJECT_SLUG_TAKEN") from exc
        issued = self._issue_key(project)
        self._db.commit()
        return project, issued

    def list(self, *, limit: int, offset: int) -> tuple[list[Project], int]:
        total = self._db.scalar(select(func.count()).select_from(Project)) or 0
        items = self._db.scalars(
            select(Project).order_by(Project.created_at.desc()).limit(limit).offset(offset)
        ).all()
        return list(items), total

    def get(self, project_id: uuid.UUID) -> Project:
        project = self._db.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found.", code="PROJECT_NOT_FOUND")
        return project

    def update(self, project_id: uuid.UUID, data: ProjectUpdate) -> Project:
        project = self.get(project_id)
        changes = data.model_dump(exclude_unset=True)
        for required in ("name", "recipient_email"):
            if required in changes and changes[required] is None:
                raise AppError(f"{required} cannot be null.", code="VALIDATION_ERROR")
        for list_field in ("allowed_origins", "allowed_recipient_domains"):
            if list_field in changes and changes[list_field] is None:
                changes[list_field] = []
        if "sender_email" in changes:
            self._check_sender_domain(changes["sender_email"])
        for field, value in changes.items():
            setattr(project, field, value)
        self._db.commit()
        self._db.refresh(project)
        return project

    def set_active(self, project_id: uuid.UUID, active: bool) -> Project:
        project = self.get(project_id)
        project.is_active = active
        self._db.commit()
        self._db.refresh(project)
        return project

    def delete(self, project_id: uuid.UUID) -> None:
        project = self.get(project_id)
        self._db.delete(project)
        self._db.commit()

    def usage(self, project_id: uuid.UUID) -> ProjectUsage:
        project = self.get(project_id)
        by_status = dict(
            self._db.execute(
                select(EmailLog.status, func.count())
                .where(EmailLog.project_id == project.id)
                .group_by(EmailLog.status)
            ).all()
        )
        by_type = dict(
            self._db.execute(
                select(EmailLog.email_type, func.count())
                .where(EmailLog.project_id == project.id)
                .group_by(EmailLog.email_type)
            ).all()
        )
        today = emails_sent_today(self._db, project.id)
        contacts = (
            self._db.scalar(select(func.count()).where(ContactSubmission.project_id == project.id))
            or 0
        )
        last_used = self._db.scalar(
            select(func.max(ApiKey.last_used_at)).where(ApiKey.project_id == project.id)
        )
        return ProjectUsage(
            project_id=project.id,
            emails_total=sum(by_status.values()),
            emails_today=today,
            daily_quota=project.daily_quota,
            daily_quota_remaining=max(project.daily_quota - today, 0),
            emails_by_status=by_status,
            emails_by_type=by_type,
            contact_submissions_total=contacts,
            api_key_last_used_at=last_used,
        )

    # --- API keys -----------------------------------------------------------

    def list_keys(self, project_id: uuid.UUID) -> list[ApiKey]:
        self.get(project_id)
        return list(
            self._db.scalars(
                select(ApiKey)
                .where(ApiKey.project_id == project_id)
                .order_by(ApiKey.is_active.desc(), ApiKey.created_at.desc())
            ).all()
        )

    def regenerate_key(self, project_id: uuid.UUID) -> IssuedKey:
        """Revoke every active key of the project and issue a new one."""
        project = self.get(project_id)
        self._revoke_all(project.id)
        issued = self._issue_key(project)
        self._db.commit()
        return issued

    def revoke_key(self, project_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey:
        key = self._db.scalar(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.project_id == project_id)
        )
        if key is None:
            raise NotFoundError("API key not found.", code="API_KEY_NOT_FOUND")
        if key.is_active:
            key.is_active = False
            key.revoked_at = datetime.now(UTC)
            self._db.commit()
        return key

    def _revoke_all(self, project_id: uuid.UUID) -> None:
        self._db.execute(
            update(ApiKey)
            .where(ApiKey.project_id == project_id, ApiKey.is_active.is_(True))
            .values(is_active=False, revoked_at=datetime.now(UTC))
        )

    def _issue_key(self, project: Project) -> IssuedKey:
        generated = generate_api_key()
        record = ApiKey(project_id=project.id, key_prefix=generated.prefix, key_hash=generated.hash)
        self._db.add(record)
        self._db.flush()
        return IssuedKey(record=record, plaintext=generated.plaintext)

    def _check_sender_domain(self, sender_email: str | None) -> None:
        if not sender_email:
            return
        allowed = self._settings.sender_domains
        domain = sender_email.rsplit("@", 1)[1].lower()
        if allowed and domain not in allowed:
            raise SenderDomainNotAllowedError(
                f"Sender domain '{domain}' is not allowed. Add it to ALLOWED_SENDER_DOMAINS "
                "after verifying it in Resend."
            )


def authenticate_api_key(db: Session, raw_key: str) -> Project | None:
    """Return the active project owning ``raw_key``, or None."""
    if not looks_like_api_key(raw_key):
        return None
    row = db.execute(
        select(ApiKey, Project)
        .join(Project, Project.id == ApiKey.project_id)
        .where(ApiKey.key_hash == hash_api_key(raw_key), ApiKey.is_active.is_(True))
    ).first()
    if row is None:
        return None
    key, project = row  # Row unpacks like a tuple
    now = datetime.now(UTC)
    # Throttle writes: record usage at most once a minute per key.
    if key.last_used_at is None or (now - key.last_used_at).total_seconds() > 60:
        key.last_used_at = now
        db.commit()
    return project


def emails_sent_today(db: Session, project_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count()).where(
                EmailLog.project_id == project_id, EmailLog.created_at >= start_of_utc_day()
            )
        )
        or 0
    )
