"""Transactional email: a template made sendable over the API, backed by a workflow that runs once per send."""

from products.messaging.backend.facade.contracts import DeliveryUnavailable, QueuedEmail, TransactionalEmailError
from products.messaging.backend.services.transactional_email import make_transactional, send_transactional_email

__all__ = [
    "DeliveryUnavailable",
    "QueuedEmail",
    "TransactionalEmailError",
    "make_transactional",
    "send_transactional_email",
]
