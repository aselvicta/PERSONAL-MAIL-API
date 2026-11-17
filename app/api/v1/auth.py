"""Administrator authentication. There is deliberately no public registration."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_client_ip, get_current_admin, get_rate_limiter
from app.core.config import Settings, get_settings
from app.database.session import get_db
from app.models import Administrator
from app.schemas.auth import AdminRead, LoginRequest, TokenData
from app.schemas.common import ERROR_RESPONSES, SuccessResponse, ok
from app.services import auth_service
from app.services.rate_limiter import RateLimit, RateLimiter

router = APIRouter(prefix="/auth", tags=["admin: auth"], responses=ERROR_RESPONSES)


@router.post("/login", response_model=SuccessResponse[TokenData])
def login(
    body: LoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    limiter: RateLimiter = Depends(get_rate_limiter),
    client_ip: str = Depends(get_client_ip),
) -> SuccessResponse[TokenData]:
    """Exchange administrator credentials for a short-lived JWT."""
    limiter.hit(
        RateLimit(f"login:ip:{client_ip}", settings.LOGIN_RATE_LIMIT_PER_IP, 900),
        RateLimit(f"login:email:{body.email}", settings.LOGIN_RATE_LIMIT_PER_IP, 900),
    )
    token = auth_service.login(db, settings, body.email, body.password)
    return ok("Login successful.", TokenData(access_token=token.token, expires_in=token.expires_in))


@router.get("/me", response_model=SuccessResponse[AdminRead])
def me(admin: Administrator = Depends(get_current_admin)) -> SuccessResponse[AdminRead]:
    return ok("Authenticated administrator.", AdminRead.model_validate(admin))
