"""Pure-ASGI middleware: body size limit, public-endpoint CORS, security headers."""

from __future__ import annotations

import json
from collections.abc import Iterable

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def _error_body(message: str, code: str) -> bytes:
    return json.dumps({"success": False, "message": message, "error": {"code": code}}).encode()


class BodySizeLimitMiddleware:
    """Reject request bodies larger than ``max_bytes`` with 413.

    Checks Content-Length up front and also counts streamed (chunked) bodies.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = Headers(scope=scope).get("content-length")
        if content_length is not None:
            try:
                too_large = int(content_length) > self.max_bytes
            except ValueError:
                too_large = True
            if too_large:
                await self._reject(send)
                return

        received = 0
        response_started = False
        rejected = False

        async def limited_receive() -> Message:
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Answer 413 ourselves; frameworks may otherwise turn a
                    # read error into a generic 400. Then tell the app the
                    # client went away and drop anything it tries to send.
                    rejected = True
                    if not response_started:
                        await self._reject(send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if rejected:
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        await self.app(scope, limited_receive, guarded_send)

    @staticmethod
    async def _reject(send: Send) -> None:
        body = _error_body("Request body is too large.", "PAYLOAD_TOO_LARGE")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class PublicCORSMiddleware:
    """CORS for the public, credential-less contact endpoint.

    Each project keeps its own ``allowed_origins`` in the database, and the
    endpoint enforces that list server-side. The browser-level CORS response
    therefore reflects any origin for these paths; the server-side check
    decides. No cookies or credentials are ever allowed.
    """

    def __init__(self, app: ASGIApp, paths: Iterable[str]) -> None:
        self.app = app
        self.paths = frozenset(paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] not in self.paths:
            await self.app(scope, receive, send)
            return

        origin = Headers(scope=scope).get("origin")
        if not origin:
            await self.app(scope, receive, send)
            return

        if scope["method"] == "OPTIONS":
            headers = [
                (b"access-control-allow-origin", origin.encode("latin-1")),
                (b"access-control-allow-methods", b"POST, OPTIONS"),
                (b"access-control-allow-headers", b"Content-Type, Authorization"),
                (b"access-control-max-age", b"600"),
                (b"vary", b"Origin"),
                (b"content-length", b"0"),
            ]
            await send({"type": "http.response.start", "status": 204, "headers": headers})
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_with_cors(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Access-Control-Allow-Origin"] = origin
                headers.append("Vary", "Origin")
            await send(message)

        await self.app(scope, receive, send_with_cors)


class SecurityHeadersMiddleware:
    """Conservative headers for a JSON API."""

    def __init__(self, app: ASGIApp, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        docs = scope["path"] in {"/docs", "/redoc"}

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "no-referrer")
                if not docs:
                    headers.setdefault("Cache-Control", "no-store")
                if self.hsts:
                    headers.setdefault(
                        "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
                    )
            await send(message)

        await self.app(scope, receive, send_with_headers)
