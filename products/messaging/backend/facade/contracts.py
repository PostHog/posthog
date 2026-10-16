from dataclasses import dataclass
from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum


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


TEMPLATE_KEY_PATTERN = r"^[a-zA-Z0-9_-]+$"
TEMPLATE_KEY_MAX_LENGTH = 400


class TemplateManagedBy(LabeledStrEnum):
    GUI = "gui", "GUI"
    CODE = "code", "Code"


class TemplateUploadResult(LabeledStrEnum):
    CREATED = "created", "Created"
    UPDATED = "updated", "Updated"
    UNCHANGED = "unchanged", "Unchanged"


@frozen
class TemplateSource:
    """Where the uploaded file lives. A part that is None leaves the stored part as it is."""

    repository: str | None
    path: str | None
    ref: str | None


@frozen
class TemplateUpload:
    key: str
    name: str
    subject: str
    html: str
    text: str
    preheader: str
    # The editor's design for the html, so the template opens in the visual editor.
    design: dict[str, Any]
    source: TemplateSource | None
