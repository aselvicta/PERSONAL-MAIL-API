"""Application factory and ASGI entry point (``uvicorn app.main:app``)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin_ui import mount_admin_ui
from app.api import health
from app.api.v1 import auth, contact, emails, notifications, projects, webhooks
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import (
    BodySizeLimitMiddleware,
    PublicCORSMiddleware,
    SecurityHeadersMiddleware,
)

logger = logging.getLogger(__name__)

API_V1_PREFIX = "/api/v1"
PUBLIC_BROWSER_PATHS = (f"{API_V1_PREFIX}/contact",)

OPENAPI_TAGS = [
    {
        "name": "contact",
        "description": "Public contact form endpoint (no private key in browsers).",
    },
    {"name": "emails", "description": "Transactional email and email logs. Project API key."},
    {"name": "notifications", "description": "Notify the project owner. Project API key."},
    {"name": "admin: auth", "description": "Administrator login."},
    {"name": "admin: projects", "description": "Project and API key administration. Admin JWT."},
    {"name": "webhooks", "description": "Resend delivery events (Svix-signed)."},
    {"name": "health", "description": "Liveness and database health."},
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.LOG_LEVEL)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "Starting %s v%s (env=%s)",
            settings.APP_NAME,
            settings.APP_VERSION,
            settings.APP_ENV.value,
        )
        if not settings.RESEND_API_KEY:
            logger.warning("RESEND_API_KEY is not set: email sending is disabled")
        if not settings.RESEND_WEBHOOK_SECRET:
            logger.warning("RESEND_WEBHOOK_SECRET is not set: webhooks will be rejected")
        yield

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Self-hostable, centralised email API built with FastAPI and Resend.\n\n"
            "**One API. All your applications. Your email infrastructure.**\n\n"
            "* Browser contact forms call `POST /api/v1/contact` with the public project slug.\n"
            "* Backends call the other endpoints with `Authorization: Bearer pmk_...`.\n"
            "* Administrators log in at `/api/v1/auth/login` and use the returned JWT."
        ),
        openapi_tags=OPENAPI_TAGS,
        docs_url="/docs" if settings.DOCS_ENABLED else None,
        redoc_url="/redoc" if settings.DOCS_ENABLED else None,
        openapi_url="/openapi.json" if settings.DOCS_ENABLED else None,
        lifespan=lifespan,
    )

    # Middleware runs in reverse order of registration (last added = outermost).
    # CORS is a browser convenience, not a security boundary.
    if settings.CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
            max_age=600,
        )
    app.add_middleware(PublicCORSMiddleware, paths=PUBLIC_BROWSER_PATHS)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.MAX_REQUEST_BODY_BYTES)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)

    register_exception_handlers(app)

    api_v1 = APIRouter(prefix=API_V1_PREFIX)
    for module in (contact, emails, notifications, auth, projects, webhooks):
        api_v1.include_router(module.router)
    app.include_router(api_v1)
    app.include_router(health.router)
    if settings.ADMIN_UI_ENABLED:
        mount_admin_ui(app)
    return app


app = create_app()
