"""Transactional email: a template made sendable over the API, backed by a workflow that runs once per send."""

from products.messaging.backend.facade.contracts import DeliveryUnavailable, QueuedEmail, TransactionalEmailError
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

__all__ = [
    "SENDER_ADDRESS_MAX_LENGTH",
    "DeliveryUnavailable",
    "QueuedEmail",
    "TransactionalEmailError",
    "TransactionalEmailStage",
    "check_transactional_update",
    "lock_transactional_workflow_id",
    "make_transactional",
    "observe_transactional_email_stage",
    "send_transactional_email",
    "sender_address_error",
    "sync_transactional_workflow",
    "transactional_email_stage",
]
