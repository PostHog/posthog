"""Transactional emails: a message template made sendable over the API, backed by a one-step workflow."""

from products.workflows.backend.facade.contracts import (
    EMAIL_FROM_CODE_FLAG,
    CodeEmailWorkflow,
    TransactionalEmailContent,
    TransactionalEmailContentInvalid,
    TransactionalEmailSenderRequired,
    TransactionalEmailSenderUnavailable,
    WorkflowNotFound,
)
from products.workflows.backend.services.transactional_email_workflows import (
    code_send_sender_id,
    create_code_email_workflow,
    create_transactional_email_workflow,
    get_code_email_workflows,
    resolve_transactional_email_sender,
    update_code_email_labels,
    update_transactional_email_workflow,
)

__all__ = [
    "CodeEmailWorkflow",
    "EMAIL_FROM_CODE_FLAG",
    "TransactionalEmailContent",
    "TransactionalEmailContentInvalid",
    "TransactionalEmailSenderRequired",
    "TransactionalEmailSenderUnavailable",
    "WorkflowNotFound",
    "code_send_sender_id",
    "create_code_email_workflow",
    "create_transactional_email_workflow",
    "get_code_email_workflows",
    "resolve_transactional_email_sender",
    "update_code_email_labels",
    "update_transactional_email_workflow",
]
