from dataclasses import dataclass
from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen


class UnlayerError(Exception):
    pass


class UnlayerNotConfiguredError(UnlayerError):
    pass


class UnlayerRenderError(UnlayerError):
    pass


@dataclass(frozen=True)
class EmailTemplateSummary:
    id: UUID
    name: str
    subject: str


@dataclass(frozen=True)
class EmailTemplateContent:
    id: UUID
    name: str
    # The template's email body: subject, html, text and the editor design.
    email: dict[str, Any]


class TransactionalEmailError(Exception):
    """A send the caller has to fix before retrying. `code` is stable for API clients."""

    code = "invalid"


class TemplateNotSendable(TransactionalEmailError):
    code = "template_not_sendable"


class MarketingTemplate(TransactionalEmailError):
    code = "marketing_template"


class SenderUnavailable(TransactionalEmailError):
    code = "sender_unavailable"


class TemplateNotTransactional(TransactionalEmailError):
    code = "template_not_transactional"


class TransactionalEmailPaused(TransactionalEmailError):
    code = "transactional_email_paused"


class InvalidRecipient(TransactionalEmailError):
    code = "invalid_recipient"


class QuotaLimited(TransactionalEmailError):
    code = "quota_limited"


class DeliveryUnavailable(Exception):
    """The email pipeline did not accept the send. Safe to retry."""


@frozen
class QueuedEmail:
    message_id: str
