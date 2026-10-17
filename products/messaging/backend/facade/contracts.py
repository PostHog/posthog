from collections.abc import Mapping
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
    SUPERSEDED = "superseded", "Superseded"


class ContentHashState(LabeledStrEnum):
    """How the content hash a send carries compares with the template's published content."""

    NONE = "none", "None"
    CURRENT = "current", "Current"
    SUPERSEDED = "superseded", "Superseded"
    OUTDATED = "outdated", "Outdated"


@frozen
class TemplateReference:
    """A template a send names by exactly one of `key` or `id`."""

    key: str | None
    id: UUID | None
    hash: str | None


@frozen
class TemplateWriteIntent:
    """A write to a template: the API action that carries it and its whole request body."""

    action: str
    payload: Mapping[str, Any]


class TemplateWriteRefused(Exception):
    """The template refuses this write. `code` is stable for API clients; `detail`, `why` and `fix` are written for
    the caller."""

    def __init__(self, *, code: str, detail: str, why: str, fix: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.why = why
        self.fix = fix


class TemplateManagedByCode(TemplateWriteRefused):
    """The template is managed by code, so it refuses every write but an upload, a send or a release."""

    def __init__(self, *, detail: str, why: str, fix: str) -> None:
        super().__init__(code="immutable", detail=detail, why=why, fix=fix)


class TemplateKeyRefused(TemplateWriteRefused):
    """The template can't take this key."""


@frozen
class TemplateSource:
    """Where the uploaded file lives. A part that is None leaves the stored part as it is."""

    repository: str | None
    path: str | None
    ref: str | None


@frozen
class TemplateChangePrompt:
    """What a person hands their coding agent to change a template managed by code: the start of the sentence that
    asks for the change, and the "About this file" block that follows it after a blank line."""

    starter: str
    context: str


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
    # An automatic upload sets it, so it never publishes content that newer content already replaced.
    if_not_superseded: bool
