"""Transactional email: a template made sendable over the API, backed by a workflow that runs once per send."""

from products.messaging.backend.facade.contracts import DeliveryUnavailable, QueuedEmail, TransactionalEmailError
from products.messaging.backend.services.transactional_email import (
    check_transactional_update,
    lock_transactional_workflow_id,
    make_transactional,
    send_transactional_email,
    sync_transactional_workflow,
)

__all__ = [
    "DeliveryUnavailable",
    "QueuedEmail",
    "TransactionalEmailError",
    "check_transactional_update",
    "lock_transactional_workflow_id",
    "make_transactional",
    "send_transactional_email",
    "sync_transactional_workflow",
]
