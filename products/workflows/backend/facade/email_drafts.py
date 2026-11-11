"""First drafts of emails to the people another product points at, written by a model or from a template."""

from products.workflows.backend.facade.contracts import EmailDraft, EmailDraftSourceForbidden, EmailDraftSourceNotFound
from products.workflows.backend.facade.enums import EmailDraftFallbackReason, EmailDraftOrigin, EmailDraftSource
from products.workflows.backend.services.email_draft import write_email_draft

__all__ = [
    "EmailDraft",
    "EmailDraftFallbackReason",
    "EmailDraftOrigin",
    "EmailDraftSource",
    "EmailDraftSourceForbidden",
    "EmailDraftSourceNotFound",
    "write_email_draft",
]
