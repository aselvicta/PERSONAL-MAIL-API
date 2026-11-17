"""Logging setup with defensive redaction of credentials.

Code should never log secrets in the first place. The redaction filter is a
second line of defence in case a library or exception message contains one.
"""

from __future__ import annotations

import logging
import re
import sys

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Personal Mail API project keys
    (re.compile(r"pmk_[A-Za-z0-9_\-]{8,}"), "pmk_[REDACTED]"),
    # Resend API keys
    (re.compile(r"\bre_[A-Za-z0-9_]{8,}"), "re_[REDACTED]"),
    # Svix / Resend webhook secrets
    (re.compile(r"whsec_[A-Za-z0-9+/=]{8,}"), "whsec_[REDACTED]"),
    # Bearer tokens (JWTs, API keys)
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"), r"\1[REDACTED]"),
    # Passwords embedded in connection URLs
    (re.compile(r"(\w+://[^:/\s]+:)[^@\s]+(@)"), r"\1[REDACTED]\2"),
)


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        if record.exc_info and not record.exc_text:
            formatter = logging.Formatter()
            record.exc_text = redact(formatter.formatException(record.exc_info))
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    handler.addFilter(RedactingFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Route uvicorn's loggers through the same redacting handler.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
