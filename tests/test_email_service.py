from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.models import EmailLog, EmailStatus, EmailType, Project
from app.services.email_service import EmailContent, EmailService
from app.services.resend_service import ProviderErrorCode, SendResult, SendStatus
from tests.conftest import FakeResendService


@pytest.fixture
def service(
    db_session: Session, fake_resend: FakeResendService, settings: Settings
) -> EmailService:
    return EmailService(db=db_session, resend_service=fake_resend, settings=settings)  # type: ignore[arg-type]


CONTENT = EmailContent(
    to="user@example.com",
    subject="Welcome to CareerDocs",
    html="<h1>Welcome!</h1>",
    text="Welcome!",
    reply_to=("support@example.com",),
)


def test_accepted_email_is_logged_with_message_id(
    service: EmailService, fake_resend: FakeResendService, project: Project, db_session: Session
) -> None:
    result = service.dispatch(project=project, email_type=EmailType.TRANSACTIONAL, content=CONTENT)

    assert result.accepted
    log = db_session.scalars(select(EmailLog)).one()
    assert log.id == result.log.id
    assert log.project_id == project.id
    assert log.status == EmailStatus.ACCEPTED
    assert log.resend_message_id == "msg_fake_1"
    assert log.provider == "resend"
    assert log.email_type == "transactional"
    assert log.recipient == "user@example.com"
    assert log.error_code is None

    (sent,) = fake_resend.sent
    assert sent.idempotency_key == f"email-log/{log.id}"
    assert sent.from_email == "portfolio@mail.example.com"
    assert sent.from_name == "Portfolio"
    assert list(sent.reply_to) == ["support@example.com"]
    assert sent.tags == {"project": "portfolio", "email_type": "transactional"}


def test_provider_failure_is_logged_as_failed(
    service: EmailService, fake_resend: FakeResendService, project: Project, db_session: Session
) -> None:
    fake_resend.result = SendResult(
        status=SendStatus.REJECTED,
        error_code=ProviderErrorCode.PROVIDER_REJECTED,
        error_message="The domain is not verified.",
    )

    result = service.dispatch(project=project, email_type=EmailType.NOTIFICATION, content=CONTENT)

    assert not result.accepted
    log = db_session.scalars(select(EmailLog)).one()
    assert log.status == EmailStatus.FAILED
    assert log.error_code == "PROVIDER_REJECTED"
    assert log.error_message == "The domain is not verified."
    assert log.resend_message_id is None


def test_sender_falls_back_to_default_identity(
    service: EmailService, fake_resend: FakeResendService, project: Project, settings: Settings
) -> None:
    project.sender_email = None
    project.sender_name = None

    service.dispatch(project=project, email_type=EmailType.NOTIFICATION, content=CONTENT)

    (sent,) = fake_resend.sent
    assert sent.from_email == settings.DEFAULT_FROM_EMAIL
    assert sent.from_name == settings.DEFAULT_FROM_NAME


def test_missing_sender_configuration_fails_before_logging(
    db_session: Session,
    fake_resend: FakeResendService,
    project: Project,
    settings: Settings,
) -> None:
    project.sender_email = None
    service = EmailService(
        db=db_session,
        resend_service=fake_resend,  # type: ignore[arg-type]
        settings=settings.model_copy(update={"DEFAULT_FROM_EMAIL": None}),
    )

    with pytest.raises(ConfigurationError) as exc_info:
        service.dispatch(project=project, email_type=EmailType.NOTIFICATION, content=CONTENT)

    assert exc_info.value.code == "SENDER_NOT_CONFIGURED"
    assert fake_resend.sent == []
    assert db_session.scalars(select(EmailLog)).all() == []


def test_header_injection_is_rejected_before_logging(
    service: EmailService, fake_resend: FakeResendService, project: Project, db_session: Session
) -> None:
    bad = EmailContent(to="user@example.com", subject="Hi\r\nBcc: x@example.com", text="hi")

    with pytest.raises(ValueError):
        service.dispatch(project=project, email_type=EmailType.TRANSACTIONAL, content=bad)

    assert fake_resend.sent == []
    assert db_session.scalars(select(EmailLog)).all() == []
