from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import Settings
from app.core.security import (
    JWT_AUDIENCE,
    create_access_token,
    decode_access_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    looks_like_api_key,
    verify_password,
)
from app.services.auth_service import WeakPasswordError, validate_password_strength


def test_password_hash_is_argon2_and_verifies() -> None:
    hashed = hash_password("a-very-strong-password")
    assert hashed.startswith("$argon2id$")
    assert "a-very-strong-password" not in hashed
    assert verify_password("a-very-strong-password", hashed)
    assert not verify_password("wrong-password", hashed)
    assert not verify_password("anything", None)
    assert not verify_password("anything", "not-a-hash")


@pytest.mark.parametrize("password", ["short", "aaaaaaaaaaaaaaaa", " padded-password-123 "])
def test_weak_passwords_are_rejected(password: str) -> None:
    with pytest.raises(WeakPasswordError):
        validate_password_strength(password)


def test_jwt_roundtrip(settings: Settings) -> None:
    admin_id = uuid.uuid4()
    token = create_access_token(admin_id, settings)
    assert token.expires_in == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert decode_access_token(token.token, settings) == admin_id


def _sign(settings: Settings, **claims: object) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid.uuid4()),
        "aud": JWT_AUDIENCE,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    payload.update(claims)
    return jwt.encode(payload, settings.JWT_SECRET_KEY.get_secret_value(), algorithm="HS256")


def test_expired_jwt_is_rejected(settings: Settings) -> None:
    token = _sign(settings, exp=datetime.now(UTC) - timedelta(seconds=1))
    assert decode_access_token(token, settings) is None


def test_jwt_with_wrong_audience_or_type_is_rejected(settings: Settings) -> None:
    assert decode_access_token(_sign(settings, aud="someone-else"), settings) is None
    assert decode_access_token(_sign(settings, type="refresh"), settings) is None


def test_jwt_signed_with_other_secret_is_rejected(settings: Settings) -> None:
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "aud": JWT_AUDIENCE, "type": "access", "exp": 9999999999},
        "attacker-secret-attacker-secret-attacker",
        algorithm="HS256",
    )
    assert decode_access_token(forged, settings) is None


def test_unsigned_jwt_is_rejected(settings: Settings) -> None:
    unsigned = jwt.encode(
        {"sub": str(uuid.uuid4()), "aud": JWT_AUDIENCE, "type": "access", "exp": 9999999999},
        key=None,
        algorithm="none",
    )
    assert decode_access_token(unsigned, settings) is None


def test_api_keys_are_random_prefixed_and_hashed() -> None:
    first, second = generate_api_key(), generate_api_key()
    assert first.plaintext != second.plaintext
    assert first.plaintext.startswith("pmk_")
    assert looks_like_api_key(first.plaintext)
    assert len(first.plaintext) >= 47  # pmk_ + 43 chars (256 bits)
    assert first.prefix == first.plaintext[:12]
    assert first.hash == hash_api_key(first.plaintext)
    assert first.plaintext not in first.hash
    assert not looks_like_api_key("pmk_short")
    assert not looks_like_api_key("Bearer something-else-entirely-0123456789abcdef")
