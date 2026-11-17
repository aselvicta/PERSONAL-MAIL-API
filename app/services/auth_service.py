"""Administrator authentication and account management."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import (
    MIN_ADMIN_PASSWORD_LENGTH,
    AccessToken,
    create_access_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.models import Administrator

logger = logging.getLogger(__name__)


class WeakPasswordError(ValueError):
    pass


def validate_password_strength(password: str) -> None:
    if len(password) < MIN_ADMIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"Password must be at least {MIN_ADMIN_PASSWORD_LENGTH} characters long."
        )
    if password.strip() != password or len(set(password)) < 6:
        raise WeakPasswordError("Password is too weak.")


def create_admin(db: Session, email: str, password: str) -> Administrator:
    validate_password_strength(password)
    email = email.strip().lower()
    if db.scalar(select(Administrator.id).where(Administrator.email == email)):
        raise ConflictError("An administrator with this email already exists.")
    admin = Administrator(email=email, hashed_password=hash_password(password))
    db.add(admin)
    db.commit()
    return admin


def set_admin_password(db: Session, email: str, password: str) -> Administrator | None:
    validate_password_strength(password)
    admin = db.scalar(select(Administrator).where(Administrator.email == email.strip().lower()))
    if admin is None:
        return None
    admin.hashed_password = hash_password(password)
    admin.is_active = True
    db.commit()
    return admin


def ensure_admin(db: Session, email: str, password: str) -> str:
    """Make sure an active administrator exists with exactly this password.

    Idempotent, so it is safe to run on every container start. Returns
    "created", "updated" or "unchanged". Never logs or returns the password.
    """
    validate_password_strength(password)
    email = email.strip().lower()
    admin = db.scalar(select(Administrator).where(Administrator.email == email))
    if admin is None:
        db.add(Administrator(email=email, hashed_password=hash_password(password)))
        try:
            db.commit()
        except IntegrityError:  # another instance created it at the same moment
            db.rollback()
            return "unchanged"
        return "created"
    if verify_password(password, admin.hashed_password) and admin.is_active:
        return "unchanged"
    admin.hashed_password = hash_password(password)
    admin.is_active = True
    db.commit()
    return "updated"


def login(db: Session, settings: Settings, email: str, password: str) -> AccessToken:
    admin = db.scalar(select(Administrator).where(Administrator.email == email.strip().lower()))
    # verify_password checks against a dummy hash when the admin does not
    # exist, so response timing does not reveal registered emails.
    valid = verify_password(password, admin.hashed_password if admin else None)
    if not admin or not valid or not admin.is_active:
        logger.info("Failed administrator login attempt")
        raise AuthenticationError("Invalid email or password.", code="INVALID_CREDENTIALS")
    if password_needs_rehash(admin.hashed_password):
        admin.hashed_password = hash_password(password)
        db.commit()
    return create_access_token(admin.id, settings)
