"""Transactional email: a template made sendable over the API, backed by a workflow that runs once per send."""

from products.messaging.backend.facade.contracts import (
    EmailSendCommand,
    EmailSendOutcome,
    Queued,
    Rejected,
    TransactionalEmailError,
    Unavailable,
)
from products.messaging.backend.services.transactional_email import (
    SENDER_ADDRESS_MAX_LENGTH,
    make_transactional,
    send_email,
    sender_address_error,
)

__all__ = [
    "SENDER_ADDRESS_MAX_LENGTH",
    "EmailSendCommand",
    "EmailSendOutcome",
    "Queued",
    "Rejected",
    "TransactionalEmailError",
    "Unavailable",
    "make_transactional",
    "send_email",
    "sender_address_error",
]
