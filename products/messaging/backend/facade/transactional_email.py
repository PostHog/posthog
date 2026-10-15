"""Transactional email: a template made sendable over the API, backed by a workflow that runs once per send."""

from products.messaging.backend.facade.contracts import TransactionalEmailError
from products.messaging.backend.services.transactional_email import make_transactional

__all__ = [
    "TransactionalEmailError",
    "make_transactional",
]
