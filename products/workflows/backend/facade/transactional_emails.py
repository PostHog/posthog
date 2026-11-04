"""Transactional emails: a message template made sendable over the API, backed by a one-step workflow."""

from products.workflows.backend.facade.contracts import (
    TransactionalEmailContent,
    TransactionalEmailContentInvalid,
    TransactionalEmailSandboxSender,
    TransactionalEmailSenderUnavailable,
    WorkflowNotFound,
)
from products.workflows.backend.services.transactional_email_workflows import (
    create_transactional_email_workflow,
    resolve_transactional_email_sender,
    update_transactional_email_workflow,
)

__all__ = [
    "TransactionalEmailContent",
    "TransactionalEmailContentInvalid",
    "TransactionalEmailSandboxSender",
    "TransactionalEmailSenderUnavailable",
    "WorkflowNotFound",
    "create_transactional_email_workflow",
    "resolve_transactional_email_sender",
    "update_transactional_email_workflow",
]
