"""Health check, used by Docker and Render (health check path ``/health``)."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.database.session import get_db
from app.schemas.common import SuccessResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


class HealthData(BaseModel):
    status: Literal["ok", "degraded"]
    app: str
    version: str
    environment: str
    database: Literal["ok", "unavailable"]
    email_provider: Literal["configured", "not_configured"]


# HEAD is allowed too: uptime monitors such as UptimeRobot send HEAD requests.
@router.head("/health", include_in_schema=False)
@router.get(
    "/health",
    response_model=SuccessResponse[HealthData],
    responses={503: {"model": SuccessResponse[HealthData]}},
)
def health(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> JSONResponse:
    try:
        db.execute(text("SELECT 1"))
        database: Literal["ok", "unavailable"] = "ok"
    except Exception:
        # Log the failure without leaking connection details to the caller.
        logger.exception("Health check: database unavailable")
        database = "unavailable"

    healthy = database == "ok"
    data = HealthData(
        status="ok" if healthy else "degraded",
        app=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.APP_ENV.value,
        database=database,
        email_provider="configured" if settings.RESEND_API_KEY else "not_configured",
    )
    body = SuccessResponse[HealthData](
        success=healthy,
        message="Service is healthy." if healthy else "Service is degraded.",
        data=data,
    )
    return JSONResponse(status_code=200 if healthy else 503, content=body.model_dump())
