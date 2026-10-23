"""Transactional email: a template made sendable over the API, backed by a workflow that runs once per send."""

from products.messaging.backend.facade.contracts import (
    AcceptedSend,
    EmailSendCommand,
    EmailSendOutcome,
    Queued,
    Rejected,
    RenderedContent,
    SenderNotVerified,
    SendFrom,
    TransactionalEmailError,
    Unavailable,
)
from products.messaging.backend.services.transactional_email import (
    SENDER_ADDRESS_MAX_LENGTH,
    code_send_from,
    make_transactional,
    rendered_content,
    send_email,
    sender_address_error,
)

__all__ = [
    "SENDER_ADDRESS_MAX_LENGTH",
    "AcceptedSend",
    "EmailSendCommand",
    "EmailSendOutcome",
    "Queued",
    "Rejected",
    "RenderedContent",
    "SendFrom",
    "SenderNotVerified",
    "TransactionalEmailError",
    "Unavailable",
    "code_send_from",
    "make_transactional",
    "rendered_content",
    "send_email",
    "sender_address_error",
]
