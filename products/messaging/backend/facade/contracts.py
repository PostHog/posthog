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


class DeliveryUnavailable(Exception):
    """The email pipeline did not accept the send. Safe to retry."""


@frozen
class QueuedEmail:
    message_id: str
    # True when an earlier request with the same idempotency key already queued this email.
    replayed: bool = False


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
