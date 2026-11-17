"""Create or update the administrator defined by ADMIN_EMAIL / ADMIN_PASSWORD.

Runs once at container start (scripts/start.sh), after migrations and before
the web workers start. This exists for hosts without shell access, such as
Render's free plan. If either variable is unset, it does nothing.

Exit codes: 0 = success or nothing to do, 1 = invalid configuration.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.database.session import get_sessionmaker
from app.services.auth_service import WeakPasswordError, ensure_admin


def main() -> int:
    settings = get_settings()
    if not settings.ADMIN_EMAIL and not settings.ADMIN_PASSWORD:
        print("Admin bootstrap: ADMIN_EMAIL/ADMIN_PASSWORD not set, skipping.")
        return 0
    if not (settings.ADMIN_EMAIL and settings.ADMIN_PASSWORD):
        print("Admin bootstrap: set BOTH ADMIN_EMAIL and ADMIN_PASSWORD.", file=sys.stderr)
        return 1
    try:
        with get_sessionmaker()() as db:
            outcome = ensure_admin(
                db, settings.ADMIN_EMAIL, settings.ADMIN_PASSWORD.get_secret_value()
            )
    except WeakPasswordError as exc:
        print(f"Admin bootstrap: {exc}", file=sys.stderr)
        return 1
    print(f"Admin bootstrap: administrator {settings.ADMIN_EMAIL} {outcome}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
