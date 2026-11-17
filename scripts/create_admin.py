"""Create the first administrator, or reset an administrator's password.

Usage:
    python scripts/create_admin.py --email admin@example.com
    python scripts/create_admin.py --email admin@example.com --reset-password

The password is read from a hidden interactive prompt. For non-interactive
use (CI, a container shell), set ADMIN_PASSWORD in the environment. It is
never accepted as a command-line argument, so it cannot leak into shell
history or process listings.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import TypeAdapter, ValidationError

from app.core.exceptions import ConflictError
from app.database.session import get_sessionmaker
from app.schemas.validators import Email
from app.services.auth_service import (
    WeakPasswordError,
    create_admin,
    set_admin_password,
)


def _read_password() -> str:
    env_password = os.environ.get("ADMIN_PASSWORD")
    if env_password:
        return env_password
    if not sys.stdin.isatty():
        sys.exit("No TTY available: set ADMIN_PASSWORD in the environment.")
    password = getpass.getpass("Password (min 12 characters): ")
    if password != getpass.getpass("Confirm password: "):
        sys.exit("Passwords do not match.")
    return password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True, help="Administrator email address")
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Set a new password for an existing administrator (also re-activates it)",
    )
    args = parser.parse_args(argv)

    try:
        email = TypeAdapter(Email).validate_python(args.email)
    except ValidationError:
        print("Invalid email address.", file=sys.stderr)
        return 2

    password = _read_password()
    with get_sessionmaker()() as db:
        try:
            if args.reset_password:
                if set_admin_password(db, email, password) is None:
                    print(f"No administrator with email {email}.", file=sys.stderr)
                    return 1
                print(f"Password updated for {email}.")
            else:
                admin = create_admin(db, email, password)
                print(f"Administrator created: {admin.email} (id {admin.id}).")
        except WeakPasswordError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except ConflictError:
            print(
                f"Administrator {email} already exists. Use --reset-password to change it.",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
