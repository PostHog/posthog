"""Email status: where each transactional email is, by its message id or by its recipient."""

from products.messaging.backend.facade.contracts import EmailStatus, EmailStatusRecord
from products.messaging.backend.services.email_status import (
    EMAIL_STATUS_RETENTION,
    email_recipient_hash,
    get_email_status,
    list_email_statuses_by_recipient,
    message_created_at,
)

__all__ = [
    "EMAIL_STATUS_RETENTION",
    "EmailStatus",
    "EmailStatusRecord",
    "email_recipient_hash",
    "get_email_status",
    "list_email_statuses_by_recipient",
    "message_created_at",
]
