"""Security primitives: password hashing, admin JWTs, project API keys.

* Administrator passwords use Argon2id (``argon2-cffi`` defaults).
* Project API keys are 256-bit random secrets prefixed ``pmk_``. Because they
  are high-entropy, a SHA-256 digest is sufficient and allows an indexed
  equality lookup. Only the digest and a short display prefix are stored.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings

API_KEY_PREFIX = "pmk_"
API_KEY_DISPLAY_LENGTH = len(API_KEY_PREFIX) + 8
MIN_ADMIN_PASSWORD_LENGTH = 12
JWT_AUDIENCE = "personal-mail-api:admin"

_hasher = PasswordHasher()
# Verified against when the account does not exist, so response timing does
# not reveal which administrator emails are registered.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


# --- Passwords ------------------------------------------------------------


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    try:
        return _hasher.verify(hashed or _DUMMY_HASH, password) and hashed is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(hashed: str) -> bool:
    return _hasher.check_needs_rehash(hashed)


# --- Admin JWT ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AccessToken:
    token: str
    expires_in: int


def create_access_token(admin_id: uuid.UUID, settings: Settings) -> AccessToken:
    now = datetime.now(UTC)
    lifetime = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(admin_id),
        "aud": JWT_AUDIENCE,
        "type": "access",
        "iat": now,
        "nbf": now,
        "exp": now + lifetime,
        "jti": secrets.token_hex(8),
    }
    token = jwt.encode(
        payload, settings.JWT_SECRET_KEY.get_secret_value(), algorithm=settings.JWT_ALGORITHM
    )
    return AccessToken(token=token, expires_in=int(lifetime.total_seconds()))


def decode_access_token(token: str, settings: Settings) -> uuid.UUID | None:
    """Return the administrator id, or None if the token is invalid or expired."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],  # pinned: never trust the token's "alg"
            audience=JWT_AUDIENCE,
            options={"require": ["exp", "iat", "sub", "aud"]},
        )
        if payload.get("type") != "access":
            return None
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        return None


# --- Project API keys ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GeneratedApiKey:
    plaintext: str  # shown to the administrator exactly once
    prefix: str
    hash: str


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> GeneratedApiKey:
    plaintext = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return GeneratedApiKey(
        plaintext=plaintext,
        prefix=plaintext[:API_KEY_DISPLAY_LENGTH],
        hash=hash_api_key(plaintext),
    )


def looks_like_api_key(value: str) -> bool:
    return value.startswith(API_KEY_PREFIX) and 40 <= len(value) <= 100
