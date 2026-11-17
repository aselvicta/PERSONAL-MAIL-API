"""Minimal built-in admin UI served at ``/admin``.

A static page (HTML, CSS and plain JavaScript, no build step) that calls the
existing ``/api/v1/auth`` and ``/api/v1/admin/projects`` endpoints. It holds no
server-side logic of its own, so every permission check stays in the API.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"
ADMIN_PATH = "/admin"


router = APIRouter(include_in_schema=False)


@router.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(ADMIN_PATH)


@router.get(ADMIN_PATH)
def admin_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


def mount_admin_ui(app: FastAPI) -> None:
    app.include_router(router)
    app.mount(f"{ADMIN_PATH}/assets", StaticFiles(directory=STATIC_DIR), name="admin-assets")
