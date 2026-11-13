from dataclasses import dataclass, field
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
    attr: str | None = None
    # The total size of the files the CDP service verified before it refused, or None when it didn't verify them all.
    attachment_bytes: int | None = None


class TemplateNotSendable(TransactionalEmailError):
    code = "template_not_sendable"


class SensitiveTemplate(TransactionalEmailError):
    code = "sensitive_template"
    attr = "sensitive"


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


class InvalidIdempotencyKey(TransactionalEmailError):
    code = "invalid_idempotency_key"


class IdempotencyKeyInFlight(TransactionalEmailError):
    """The first request with this key is still being queued. Safe to retry shortly."""

    code = "idempotency_key_in_flight"


class IdempotencyKeyReused(TransactionalEmailError):
    code = "idempotency_key_reused"


class SendingSuspended(TransactionalEmailError):
    code = "sending_suspended"


class SendingPaused(TransactionalEmailError):
    code = "sending_paused"


class RecipientSuppressed(TransactionalEmailError):
    code = "recipient_suppressed"


class RecipientUnreachable(TransactionalEmailError):
    code = "recipient_unreachable"


class SenderNotVerified(TransactionalEmailError):
    code = "sender_not_verified"


class NamedSenderNotVerified(SenderNotVerified):
    attr = "from"


class FieldNotAccepted(TransactionalEmailError):
    code = "field_not_accepted"

    def __init__(self, field: str) -> None:
        super().__init__(f"PostHog doesn't take `{field}` yet.")
        self.field = field


class MessageTooLarge(TransactionalEmailError):
    code = "message_too_large"

    def __init__(self, largest_file_sha256: str | None) -> None:
        super().__init__("These files make the email larger than PostHog can send.")
        self.largest_file_sha256 = largest_file_sha256


class AttachmentNotUploaded(TransactionalEmailError):
    code = "attachment_not_uploaded"

    def __init__(self, sha256: str | None) -> None:
        super().__init__("A file this email names isn't uploaded.")
        self.sha256 = sha256


class UploadQuotaExceeded(TransactionalEmailError):
    code = "upload_quota_exceeded"


class AttachmentsRefused(TransactionalEmailError):
    attr = "attachments"

    def __init__(self, code: str, message: str, *, why: str, fix: str) -> None:
        super().__init__(message)
        self.code, self.why, self.fix = code, why, fix


@frozen
class AttachmentUploadRequest:
    sha256: str
    size: int


class AttachmentUploadStatus(LabeledStrEnum):
    PRESENT = "present", "Present"
    UPLOAD = "upload", "Upload"


@frozen
class PresentAttachment:
    sha256: str
    expires_at: datetime
    status: AttachmentUploadStatus = AttachmentUploadStatus.PRESENT


@frozen
class AttachmentUploadTarget:
    sha256: str
    url: str = field(repr=False)
    method: str
    headers: dict[str, str]
    url_expires_at: datetime
    status: AttachmentUploadStatus = AttachmentUploadStatus.UPLOAD


AttachmentUploadSlot = PresentAttachment | AttachmentUploadTarget


@frozen
class EmailAttachment:
    sha256: str
    filename: str
    content_type: str | None = None
    content_id: str | None = None


class SenderRequired(TransactionalEmailError):
    code = "sender_required"


class TooManyKeys(TransactionalEmailError):
    code = "too_many_keys"


class ContentTooLarge(TransactionalEmailError):
    code = "content_too_large"


class InvalidRequest(TransactionalEmailError):
    code = "invalid_request"


@frozen
class EmailTracking:
    opens: bool = True
    clicks: bool | None = None
    engagement: bool = True


@frozen
class CodeEmail:
    key: str
    subject: str
    html: str
    text: str
    sender: str | None
    reply_to: tuple[str, ...]
    tracking: EmailTracking
    sensitive: bool | None = None
    cc: tuple[str, ...] = ()
    bcc: tuple[str, ...] = ()
    attachments: tuple[EmailAttachment, ...] = ()


class DeliveryUnavailable(Exception):
    """The email pipeline did not accept the send. Safe to retry."""


@frozen
class QueuedEmail:
    message_id: str
    # True when an earlier request with the same idempotency key already queued this email.
    replayed: bool = False
    # The total size of the email's files, as the CDP service verified them. None when it didn't say.
    attachment_bytes: int | None = None


class SupabaseEmailActionType(LabeledStrEnum):
    """The `email_action_type` values Supabase's Send Email Hook sends."""

    SIGNUP = "signup", "Confirm sign up"
    INVITE = "invite", "Invite user"
    MAGICLINK = "magiclink", "Magic link"
    EMAIL = "email", "Email sign-in code"
    RECOVERY = "recovery", "Reset password"
    EMAIL_CHANGE = "email_change", "Change email address"
    REAUTHENTICATION = "reauthentication", "Reauthentication"
    PASSWORD_CHANGED_NOTIFICATION = "password_changed_notification", "Password changed"
    EMAIL_CHANGED_NOTIFICATION = "email_changed_notification", "Email address changed"
    PHONE_CHANGED_NOTIFICATION = "phone_changed_notification", "Phone number changed"
    IDENTITY_LINKED_NOTIFICATION = "identity_linked_notification", "Sign-in method linked"
    IDENTITY_UNLINKED_NOTIFICATION = "identity_unlinked_notification", "Sign-in method removed"
    MFA_FACTOR_ENROLLED_NOTIFICATION = "mfa_factor_enrolled_notification", "MFA method added"
    MFA_FACTOR_UNENROLLED_NOTIFICATION = "mfa_factor_unenrolled_notification", "MFA method removed"


@frozen
class SupabaseAuthEmailSettings:
    supabase_url: str
    # The secret is write-only, so callers only learn whether one is stored.
    has_hook_secret: bool
    # Supabase email action type -> message template id.
    templates: dict[str, UUID]


class SupabaseAuthEmailSettingsInvalid(Exception):
    """The settings can't be saved as given. The message says which field to fix."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


@frozen
class SupabaseHookResult:
    """What to answer Supabase. A `status` of 300 or more fails the user's auth request: Supabase returns that status
    and `message` to the client."""

    status: int
    message: str = ""
    email_action_type: str = ""
    # True when no email went out on purpose, such as an unmapped notification.
    skipped: bool = False
    # Why a send failed, for tracking. The user only sees `message`, which stays neutral.
    error_code: str = ""
    # How many emails went out. Email change can send two.
    sent_count: int = 0


class EmailDeliveryStatus(LabeledStrEnum):
    QUEUED = "queued", "Queued"
    FAILED = "failed", "Failed"
    SENT = "sent", "Sent"
    DELIVERED = "delivered", "Delivered"
    BOUNCED = "bounced", "Bounced"
    COMPLAINED = "complained", "Complained"


@frozen
class EmailStatus:
    message_id: str
    status: EmailDeliveryStatus
    created_at: datetime
    status_at: datetime
    # Why a send failed, or the bounce type of a bounced email.
    reason: str | None = None


class EmailLogEventKind(LabeledStrEnum):
    QUEUED = "queued", "Queued"
    FAILED = "failed", "Failed"
    SENT = "sent", "Sent"
    DELIVERED = "delivered", "Delivered"
    BOUNCED = "bounced", "Bounced"
    COMPLAINED = "complained", "Complained"
    OPENED = "opened", "Opened"
    CLICKED = "clicked", "Clicked"


class EmailStatsGroupBy(LabeledStrEnum):
    TEMPLATE = "template", "Template"
    SENDING_DOMAIN = "sending_domain", "Sending domain"


@frozen
class TransactionalEmailLogEntry:
    message_id: str
    created_at: datetime
    status: EmailDeliveryStatus
    status_at: datetime
    # Why a send failed, or the bounce type of a bounced email.
    reason: str | None
    recipient: str
    workflow_id: str
    template_id: str | None
    # Empty when the template was deleted.
    template_name: str
    sending_domain: str
    opened: bool
    clicked: bool


@frozen
class TransactionalEmailLogEvent:
    kind: EmailLogEventKind
    at: datetime
    reason: str | None


@frozen
class TransactionalEmailLogDetail:
    entry: TransactionalEmailLogEntry
    timeline: list[TransactionalEmailLogEvent]
    # Empty when the send never reached the provider, so nothing was rendered.
    subject: str
    distinct_id: str
    # The step that sent the email, which the rendered email is stored under. Empty when none was stored.
    action_id: str
    # True when the template keeps no rendered body.
    sensitive: bool


class EmailStatsInterval(LabeledStrEnum):
    # One bucket spans five minutes.
    MINUTE = "minute", "Minute"
    HOUR = "hour", "Hour"
    DAY = "day", "Day"


@frozen
class TransactionalEmailStatsCounts:
    sent: int
    delivered: int
    bounced: int
    complained: int
    failed: int


@frozen
class TransactionalEmailStatsBucket:
    start: datetime
    counts: TransactionalEmailStatsCounts


@frozen
class TransactionalEmailStatsOverTime:
    interval: EmailStatsInterval
    timezone: str
    buckets: list[TransactionalEmailStatsBucket]
    # The same stretch of time just before this one. None when retention no longer covers all of it.
    previous: TransactionalEmailStatsCounts | None


@frozen
class TransactionalEmailStatsRow:
    # The template id or the sending domain.
    key: str
    label: str
    sent: int
    delivered: int
    bounced: int
    complained: int
    opened: int
    clicked: int
    failed: int


@frozen
class TransactionalEmailResults:
    recipients: int
    converted: int
    revenue: float
    # Hours from the send to the first conversion, for the median converted recipient. None when nobody converted.
    median_hours_to_convert: float | None


class CodeEmailSourceOrigin(LabeledStrEnum):
    MANUAL = "manual", "Manual"
    DETECTED = "detected", "Detected from GitHub"


@frozen
class CodeManagedEmail:
    """An email sent from code under a `template_key` with no template, as the Transactional emails list shows it."""

    id: UUID
    key: str
    hog_flow_id: UUID
    description: str
    tags: tuple[str, ...]
    sensitive: bool
    source_url: str | None
    source_origin: CodeEmailSourceOrigin | None
    created_at: datetime


class CodeManagedEmailNotFound(Exception):
    pass


@frozen
class CodeEmailSourceCandidate:
    """A file in a connected GitHub repository that holds a code email's key."""

    repository: str
    path: str
    line: int
    url: str
    call_site: bool


@frozen
class CodeEmailSourceCandidates:
    candidates: tuple[CodeEmailSourceCandidate, ...]
    complete: bool


class CodeEmailSourceKeyUnsearchable(Exception):
    """GitHub can't search for the key: it is blank, spans lines, or is longer than a search allows."""


class CodeEmailSourceSearchUnavailable(Exception):
    """No GitHub installation answered the search."""

    def __init__(self, *, shed: bool) -> None:
        super().__init__("budget shed" if shed else "GitHub error")
        self.shed = shed


@frozen
class TransactionalEmailActivityEvent:
    uuid: str
    event: str
    timestamp: datetime
    current_url: str | None
    pathname: str | None
    session_id: str | None
    # Set on autocaptured events, such as `click` or `submit`.
    event_type: str | None
    # The clicked element and its parents, empty unless the event is autocaptured.
    elements_chain: str


@frozen
class TransactionalEmailActivitySession:
    session_id: str
    first_event_at: datetime
    last_event_at: datetime
    event_count: int
    # True when none of the session's events came before the send, so the person started it after the email.
    started_after_send: bool


@frozen
class TransactionalEmailActivity:
    distinct_id: str
    sent_at: datetime
    # Oldest first, ending just before the send.
    before: list[TransactionalEmailActivityEvent]
    # Oldest first, starting at the send.
    after: list[TransactionalEmailActivityEvent]
    has_more_before: bool
    has_more_after: bool
    sessions: list[TransactionalEmailActivitySession]
