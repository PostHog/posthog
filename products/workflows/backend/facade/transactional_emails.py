"""Transactional emails: a message template made sendable over the API, backed by a one-step workflow."""

from products.workflows.backend.facade.contracts import (
    TransactionalEmailContent,
    TransactionalEmailContentInvalid,
    TransactionalEmailSender,
    TransactionalEmailSenderUnavailable,
    WorkflowNotFound,
)
from products.workflows.backend.services.transactional_email_workflows import (
    code_send_sender,
    create_code_email_workflow,
    create_transactional_email_workflow,
    resolve_transactional_email_sender,
    update_transactional_email_workflow,
)

__all__ = [
    "TransactionalEmailContent",
    "TransactionalEmailContentInvalid",
    "TransactionalEmailSender",
    "TransactionalEmailSenderUnavailable",
    "WorkflowNotFound",
    "code_send_sender",
    "create_code_email_workflow",
    "create_transactional_email_workflow",
    "resolve_transactional_email_sender",
    "update_transactional_email_workflow",
]
