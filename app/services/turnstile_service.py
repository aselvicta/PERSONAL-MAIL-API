"""Cloudflare Turnstile verification for public contact forms."""

from __future__ import annotations

import logging
from functools import lru_cache

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class TurnstileVerifier:
    def __init__(self, secret_key: str | None, timeout_seconds: float = 5.0) -> None:
        self._secret = secret_key
        self._timeout = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self._secret)

    def verify(self, token: str, remote_ip: str | None = None) -> bool:
        """True only if Cloudflare confirms the token. Fails closed on any error."""
        if not self._secret or not token:
            return False
        data = {"secret": self._secret, "response": token}
        if remote_ip and remote_ip != "unknown":
            data["remoteip"] = remote_ip
        try:
            response = httpx.post(SITEVERIFY_URL, data=data, timeout=self._timeout)
            response.raise_for_status()
            return bool(response.json().get("success"))
        except (httpx.HTTPError, ValueError):
            logger.warning("Turnstile verification request failed")
            return False


@lru_cache
def get_turnstile_verifier() -> TurnstileVerifier:
    secret = get_settings().TURNSTILE_SECRET_KEY
    return TurnstileVerifier(secret.get_secret_value() if secret else None)
