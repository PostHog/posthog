from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
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


class SenderNotVerified(TransactionalEmailError):
    code = "sender_not_verified"


class SenderNotAllowed(TransactionalEmailError):
    """The caller named a `from` address that no verified sender of the project can send from."""

    code = "sender_not_allowed"


@frozen
class RenderedContent:
    """Content the caller's code rendered for one recipient. It is sent as is and never stored as a template."""

    subject: str
    html: str
    text: str


@frozen
class SendFrom:
    """A verified sender. `email` and `name` override the sender's own, on its verified domain.

    `is_default` marks the project's default sender, chosen because the send named none.
    """

    integration_id: int
    email: str | None
    name: str | None
    is_default: bool = False


@frozen
class EmailField:
    """A header or tag a code send sets on its email, by name."""

    name: str
    value: str


@frozen
class EmailAttachment:
    """A file a code send attaches to its email."""

    filename: str
    content: bytes
    content_type: str | None = None
    # Shows the file inline, where the HTML references it as `cid:<content_id>`.
    content_id: str | None = None


@frozen
class AcceptedSend:
    """What a code send sets on its own, over what its workflow's email step holds."""

    content: RenderedContent | None
    sender: SendFrom | None
    reply_to: tuple[str, ...]
    capture_engagement: bool
    cc: tuple[str, ...] = ()
    bcc: tuple[str, ...] = ()
    headers: tuple[EmailField, ...] = ()
    tags: tuple[EmailField, ...] = ()
    attachments: tuple[EmailAttachment, ...] = ()


class SendRoute(LabeledStrEnum):
    """The route a send came in on. An idempotency key used on one route is another request on the other."""

    TEMPLATE_SEND = "template_send", "messaging_templates/{id}/send/"
    SEND_EMAIL = "send_email", "messaging/send/email/"


@frozen
class StoredTemplate:
    """A template stored in PostHog, filled with `message_data`."""

    template_id: UUID
    message_data: Mapping[str, Any]
    # What a send by key sets over the template's own sender, reply-to and tracking.
    send: AcceptedSend | None = None


@frozen
class RenderedEmail:
    """Content the caller's code rendered, sent under the workflow of `key`."""

    key: str
    send: AcceptedSend


@frozen
class EmailSendCommand:
    """One email to send: who it goes to, and what it is made from."""

    team_id: int
    to: str
    # The person the send is tracked against. Without one, the recipient's address is that person.
    distinct_id: str | None
    source: StoredTemplate | RenderedEmail
    # Checked by the CDP service, so a retry with the same key queues nothing new.
    idempotency_key: str | None = None
    route: SendRoute = SendRoute.TEMPLATE_SEND


@frozen
class Queued:
    message_id: str
    # True when an earlier request with the same idempotency key already queued this email.
    replayed: bool = False


@frozen
class Rejected:
    """A send the caller has to fix before retrying. `code` is stable for API clients."""

    code: str
    detail: str
    # Set for the send checks, which say why PostHog refused the send and what to change.
    why: str | None = None
    fix: str | None = None
    # The request field that holds a refused recipient, or None when that is not known.
    recipient_field: str | None = None


@frozen
class Unavailable:
    """The email pipeline did not accept the send. Safe to retry."""


EmailSendOutcome = Queued | Rejected | Unavailable


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


class TemplateEditedInPostHog(TemplateWriteRefused):
    """An upload from code meets a template whose content people edit in PostHog."""

    def __init__(self, key: str) -> None:
        super().__init__(
            code="template_edited_in_posthog",
            detail=f"The template `{key}` is edited in PostHog, so the upload changed nothing and nothing was sent.",
            why="An upload from code would overwrite the content people edited in PostHog.",
            fix="Send the email under another `template_key`, or upload without `if_code_managed` to replace the "
            "content edited in PostHog with yours.",
        )


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
    # An automatic upload sets it, so it never publishes content that newer content already replaced.
    if_not_superseded: bool
    # A send's automatic upload sets it, so it never takes over a template people edit in PostHog.
    if_code_managed: bool = False


class EmailStatus(LabeledStrEnum):
    """Where a transactional email is. Each status ranks above the ones before it, so a late status never replaces
    a later one."""

    QUEUED = "queued", "Queued"
    WAITING = "waiting", "Waiting"
    UNKNOWN = "unknown", "Unknown"
    SKIPPED = "skipped", "Skipped"
    FAILED = "failed", "Failed"
    SENT = "sent", "Sent"
    DELIVERED = "delivered", "Delivered"
    BOUNCED = "bounced", "Bounced"
    COMPLAINED = "complained", "Complained"


@frozen
class EmailStatusRecord:
    """The latest status of one transactional email."""

    message_id: UUID
    status: EmailStatus
    created_at: datetime
    status_at: datetime
    reason: str | None


@frozen
class EmailStatusCursor:
    """Where a page of a recipient's emails ends. The next page starts after it."""

    created_at: datetime
    message_id: UUID
