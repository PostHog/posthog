"""Transactional emails: a message template made sendable over the API, backed by a one-step workflow."""

from products.workflows.backend.facade.contracts import (
    TransactionalEmailContent,
    TransactionalEmailContentInvalid,
    TransactionalEmailSenderUnavailable,
    WorkflowNotFound,
)
from products.workflows.backend.services.transactional_email_workflows import (
    create_transactional_email_workflow,
    update_transactional_email_workflow,
)

__all__ = [
    "TransactionalEmailContent",
    "TransactionalEmailContentInvalid",
    "TransactionalEmailSenderUnavailable",
    "WorkflowNotFound",
    "create_transactional_email_workflow",
    "update_transactional_email_workflow",
]
