"""Transactional email: a template made sendable over the API, backed by a workflow that runs once per send."""

from products.messaging.backend.facade.contracts import (
    DeliveryUnavailable,
    EmailDeliveryStatus,
    EmailStatus,
    QueuedEmail,
    TransactionalEmailError,
)
from products.messaging.backend.services.transactional_email import (
    SENDER_ADDRESS_MAX_LENGTH,
    TransactionalEmailStage,
    check_transactional_update,
    lock_transactional_workflow_id,
    make_transactional,
    observe_transactional_email_stage,
    send_transactional_email,
    sender_address_error,
    sync_transactional_workflow,
    transactional_email_stage,
)
from products.messaging.backend.services.transactional_email_status import get_email_status

__all__ = [
    "SENDER_ADDRESS_MAX_LENGTH",
    "DeliveryUnavailable",
    "EmailDeliveryStatus",
    "EmailStatus",
    "QueuedEmail",
    "TransactionalEmailError",
    "TransactionalEmailStage",
    "check_transactional_update",
    "get_email_status",
    "lock_transactional_workflow_id",
    "make_transactional",
    "observe_transactional_email_stage",
    "send_transactional_email",
    "sender_address_error",
    "sync_transactional_workflow",
    "transactional_email_stage",
]
