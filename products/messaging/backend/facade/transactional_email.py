"""Transactional email: a template made sendable over the API, backed by a workflow that runs once per send."""

from products.messaging.backend.facade.contracts import (
    AcceptedSend,
    EmailSendCommand,
    EmailSendOutcome,
    Queued,
    Rejected,
    RenderedContent,
    RenderedEmail,
    SenderNotVerified,
    SendFrom,
    StoredTemplate,
    TransactionalEmailError,
    Unavailable,
)
from products.messaging.backend.services.transactional_email import (
    SENDER_ADDRESS_MAX_LENGTH,
    SENDER_ADDRESS_PATTERN,
    code_send_from,
    make_transactional,
    rendered_content,
    require_code_email_access,
    send_email,
    sender_address_error,
)

__all__ = [
    "SENDER_ADDRESS_MAX_LENGTH",
    "SENDER_ADDRESS_PATTERN",
    "AcceptedSend",
    "EmailSendCommand",
    "EmailSendOutcome",
    "Queued",
    "Rejected",
    "RenderedContent",
    "RenderedEmail",
    "SendFrom",
    "SenderNotVerified",
    "StoredTemplate",
    "TransactionalEmailError",
    "Unavailable",
    "code_send_from",
    "make_transactional",
    "rendered_content",
    "require_code_email_access",
    "send_email",
    "sender_address_error",
]
