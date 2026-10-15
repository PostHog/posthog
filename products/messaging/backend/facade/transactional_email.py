"""Transactional email: send one email from a message template, triggered by the caller's code."""

from products.messaging.backend.facade.contracts import DeliveryUnavailable, QueuedEmail, TransactionalEmailError
from products.messaging.backend.services.transactional_email import send_transactional_email

__all__ = ["DeliveryUnavailable", "QueuedEmail", "TransactionalEmailError", "send_transactional_email"]
