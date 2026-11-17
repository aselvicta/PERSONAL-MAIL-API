"""Status and type enumerations.

Stored as ``varchar`` columns rather than native PostgreSQL enums, so adding a
value never needs an ``ALTER TYPE`` migration.
"""

from enum import StrEnum


class EmailType(StrEnum):
    CONTACT_NOTIFICATION = "contact_notification"
    CONTACT_ACKNOWLEDGEMENT = "contact_acknowledgement"
    TRANSACTIONAL = "transactional"
    NOTIFICATION = "notification"


class EmailStatus(StrEnum):
    # Recorded locally, not yet handed to Resend.
    PENDING = "pending"
    # Resend accepted the API request. This is NOT proof of inbox delivery.
    ACCEPTED = "accepted"
    # Resend rejected the request, timed out or was unreachable (see error_code).
    FAILED = "failed"
    # States below are only reached through verified Resend webhooks.
    SENT = "sent"
    DELIVERED = "delivered"
    DELIVERY_DELAYED = "delivery_delayed"
    BOUNCED = "bounced"
    COMPLAINED = "complained"


class ContactStatus(StrEnum):
    RECEIVED = "received"
    SENT = "sent"
    FAILED = "failed"


EMAIL_PROVIDER_RESEND = "resend"
