"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from app.models.admin import Administrator
from app.models.api_key import ApiKey
from app.models.contact import ContactSubmission
from app.models.email_event import EmailEvent
from app.models.email_log import EmailLog
from app.models.enums import ContactStatus, EmailStatus, EmailType
from app.models.project import Project
from app.models.rate_limit import RateLimitBucket

__all__ = [
    "Administrator",
    "ApiKey",
    "ContactStatus",
    "ContactSubmission",
    "EmailEvent",
    "EmailLog",
    "EmailStatus",
    "EmailType",
    "Project",
    "RateLimitBucket",
]
