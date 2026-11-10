"""Transactional emails: a message template made sendable over the API, backed by a one-step workflow."""

from products.workflows.backend.facade.contracts import (
    EMAIL_FROM_CODE_FLAG,
    TransactionalEmailCategoryType,
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
    get_transactional_email_body,
    resolve_transactional_email_sender,
    update_transactional_email_workflow,
)

__all__ = [
    "EMAIL_FROM_CODE_FLAG",
    "TransactionalEmailCategoryType",
    "TransactionalEmailContent",
    "TransactionalEmailContentInvalid",
    "TransactionalEmailSenderRequired",
    "TransactionalEmailSenderUnavailable",
    "WorkflowNotFound",
    "code_send_sender_id",
    "create_code_email_workflow",
    "create_transactional_email_workflow",
    "get_transactional_email_body",
    "resolve_transactional_email_sender",
    "update_transactional_email_workflow",
]
