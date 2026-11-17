from __future__ import annotations

from typing import Any

import pytest

from app.services.template_service import SPECS, TemplateError, TemplateName, render

SAMPLE: dict[TemplateName, dict[str, Any]] = {
    TemplateName.CONTACT_NOTIFICATION: {
        "project_name": "Portfolio",
        "sender_name": "John",
        "sender_email": "john@example.com",
        "subject": "Hello",
        "message": "Line one\nLine two",
        "submitted_at": "2026-11-17 10:00 UTC",
    },
    TemplateName.CONTACT_ACKNOWLEDGEMENT: {"project_name": "Portfolio"},
    TemplateName.NOTIFICATION: {
        "project_name": "Safari AI",
        "notification_type": "system.alert",
        "title": "Disk almost full",
        "message": "Usage at 91%",
        "details": {"host": "web-1"},
    },
    TemplateName.WELCOME: {
        "app_name": "CareerDocs",
        "name": "Jane",
        "action_url": "https://careerdocs.example.com/start",
    },
    TemplateName.PASSWORD_RESET: {
        "app_name": "CareerDocs",
        "reset_url": "https://careerdocs.example.com/reset?t=1",
    },
    TemplateName.EMAIL_VERIFICATION: {
        "app_name": "CareerDocs",
        "verification_url": "https://careerdocs.example.com/verify?t=1",
        "code": "123456",
    },
}


@pytest.mark.parametrize("name", list(TemplateName))
def test_every_template_renders_html_and_text(name: TemplateName) -> None:
    rendered = render(name, SAMPLE[name])
    assert rendered.subject and "\n" not in rendered.subject
    assert rendered.html.startswith("<!DOCTYPE html>")
    assert 'name="viewport"' in rendered.html  # responsive
    assert "{{" not in rendered.html and "{{" not in rendered.text
    assert rendered.text.strip()
    assert "<" not in rendered.text.replace("<", "", 0) or "<html" not in rendered.text


def test_all_templates_have_samples() -> None:
    assert set(SAMPLE) == set(SPECS)


def test_html_is_escaped_but_text_is_plain() -> None:
    rendered = render(
        TemplateName.WELCOME, {"app_name": "A & B", "name": '<script>alert("x")</script>'}
    )
    assert "<script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html
    assert "A &amp; B" in rendered.html
    assert '<script>alert("x")</script>' in rendered.text
    assert rendered.subject == "Welcome to A & B"


def test_subject_variables_reject_line_breaks() -> None:
    with pytest.raises(TemplateError):
        render(TemplateName.WELCOME, {"app_name": "App\r\nBcc: x@example.com"})


def test_variable_length_limit() -> None:
    with pytest.raises(TemplateError):
        render(TemplateName.WELCOME, {"app_name": "App", "message": "x" * 5001})


def test_verification_code_only() -> None:
    rendered = render(TemplateName.EMAIL_VERIFICATION, {"app_name": "App", "code": "987654"})
    assert "987654" in rendered.html and "987654" in rendered.text
    assert "expires in 60 minutes" in rendered.html
