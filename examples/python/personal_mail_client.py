"""Minimal Python client for Personal Mail API (server-side use).

pip install httpx
export MAIL_API_URL=https://your-mail-api.onrender.com
export MAIL_API_KEY=pmk_...          # private project key, keep it on the server
python personal_mail_client.py you@example.com
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx


class PersonalMailError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.details = status, code, details

    @property
    def retryable(self) -> bool:
        return self.status in (429, 503, 504)


class PersonalMailClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 15.0) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._http.request(method, path, **kwargs)
        body = response.json()
        if response.is_error or not body.get("success"):
            error = body.get("error", {})
            raise PersonalMailError(
                response.status_code,
                error.get("code", "UNKNOWN"),
                body.get("message", ""),
                error.get("details"),
            )
        return body["data"]

    def send_email(self, to: str, **fields: Any) -> dict[str, Any]:
        """Raw: subject + html/text. Template: template= + variables={...}."""
        return self._request("POST", "/api/v1/emails/send", json={"to": to, **fields})

    def notify(self, type: str, subject: str, message: str, **details: Any) -> dict[str, Any]:
        payload = {"type": type, "subject": subject, "message": message, "details": details}
        return self._request("POST", "/api/v1/notifications", json=payload)

    def list_emails(self, limit: int = 20, offset: int = 0, status: str | None = None) -> Any:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        return self._request("GET", "/api/v1/emails", params=params)

    def get_email(self, email_id: str) -> Any:
        return self._request("GET", f"/api/v1/emails/{email_id}")

    def submit_contact(
        self, project: str, name: str, email: str, message: str, **extra: Any
    ) -> Any:
        """Forward a contact form from your own backend (skips origin/Turnstile checks)."""
        payload = {"project": project, "name": name, "email": email, "message": message, **extra}
        return self._request("POST", "/api/v1/contact", json=payload)


if __name__ == "__main__":
    client = PersonalMailClient(os.environ["MAIL_API_URL"], os.environ["MAIL_API_KEY"])
    recipient = sys.argv[1] if len(sys.argv) > 1 else "delivered@resend.dev"

    accepted = client.send_email(
        recipient,
        template="welcome",
        variables={"name": "Jane", "action_url": "https://example.com/start"},
    )
    print("Accepted:", accepted)

    client.notify("user.registered", "New user registration", "Jane signed up.", Plan="Pro")
    print("Latest email:", client.get_email(accepted["id"])["status"])
