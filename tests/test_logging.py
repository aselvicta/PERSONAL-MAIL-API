from __future__ import annotations

import logging

import pytest

from app.core.logging import RedactingFilter, redact


@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        ("key=re_AbCdEf123456789", "re_AbCdEf123456789"),
        ("project key pmk_0123456789abcdefXYZ", "pmk_0123456789abcdefXYZ"),
        ("secret whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw", "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"),
        ("Authorization: Bearer eyJhbGciOi.payload.sig", "eyJhbGciOi.payload.sig"),
        ("postgresql://postgres:s3cr3t@db.x.supabase.co:5432/postgres", "s3cr3t"),
    ],
)
def test_redact_removes_secrets(raw: str, secret: str) -> None:
    assert secret not in redact(raw)


def test_redacting_filter_scrubs_log_records() -> None:
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "using %s", ("re_AbCdEf123456789",), None
    )
    RedactingFilter().filter(record)
    assert "re_AbCdEf123456789" not in record.getMessage()
