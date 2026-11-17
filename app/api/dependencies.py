"""Shared FastAPI dependencies: database-bound services and authentication."""

from __future__ import annotations

import ipaddress

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import decode_access_token
from app.database.session import get_db
from app.models import Administrator, Project
from app.services.email_service import EmailService
from app.services.project_service import ProjectService, authenticate_api_key
from app.services.rate_limiter import RateLimiter
from app.services.resend_service import ResendService, get_resend_service

# auto_error=False lets us return our own error envelope.
admin_bearer = HTTPBearer(
    auto_error=False, scheme_name="AdminJWT", description="Administrator access token"
)
project_bearer = HTTPBearer(
    auto_error=False, scheme_name="ProjectApiKey", description="Project API key (pmk_...)"
)


# --- Services -----------------------------------------------------------------


def get_email_service(
    db: Session = Depends(get_db),
    resend_service: ResendService = Depends(get_resend_service),
    settings: Settings = Depends(get_settings),
) -> EmailService:
    return EmailService(db=db, resend_service=resend_service, settings=settings)


def get_project_service(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> ProjectService:
    return ProjectService(db=db, settings=settings)


def get_rate_limiter(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> RateLimiter:
    return RateLimiter(db=db, settings=settings)


# --- Request context ----------------------------------------------------------


def get_client_ip(request: Request, settings: Settings = Depends(get_settings)) -> str:
    """Client IP address, honouring only the configured number of trusted proxies.

    Each trusted proxy appends the address it received the connection from to
    X-Forwarded-For, so the client is the Nth entry from the right. Anything
    further left was supplied by the client and cannot be trusted.
    """
    peer = request.client.host if request.client else "unknown"
    hops = settings.TRUSTED_PROXY_COUNT
    if hops > 0:
        forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",")]
        forwarded = [p for p in forwarded if p]
        if len(forwarded) >= hops:
            candidate = forwarded[-hops]
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                pass
    return peer


# --- Authentication -----------------------------------------------------------


def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(admin_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Administrator:
    if credentials is None:
        raise AuthenticationError(headers={"WWW-Authenticate": "Bearer"})
    admin_id = decode_access_token(credentials.credentials, settings)
    admin = db.get(Administrator, admin_id) if admin_id else None
    if admin is None or not admin.is_active:
        raise AuthenticationError(
            "Invalid or expired token.",
            code="INVALID_TOKEN",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return admin


def get_optional_project(
    credentials: HTTPAuthorizationCredentials | None = Depends(project_bearer),
    db: Session = Depends(get_db),
) -> Project | None:
    """The project for a presented API key, or None if no key was sent.

    An invalid or revoked key is always an error, never anonymous access.
    """
    if credentials is None:
        return None
    project = authenticate_api_key(db, credentials.credentials)
    if project is None:
        raise AuthenticationError(
            "Invalid or revoked API key.",
            code="INVALID_API_KEY",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not project.is_active:
        raise PermissionDeniedError("This project is disabled.", code="PROJECT_DISABLED")
    return project


def get_current_project(project: Project | None = Depends(get_optional_project)) -> Project:
    if project is None:
        raise AuthenticationError(
            "A project API key is required.",
            code="API_KEY_REQUIRED",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return project
