from posthog.dataclasses import frozen


class UnlayerError(Exception):
    pass


class UnlayerNotConfiguredError(UnlayerError):
    pass


class UnlayerRenderError(UnlayerError):
    pass


class TransactionalEmailError(Exception):
    """A send the caller has to fix before retrying. `code` is stable for API clients."""

    code = "invalid"


class TemplateNotSendable(TransactionalEmailError):
    code = "template_not_sendable"


class MarketingTemplate(TransactionalEmailError):
    code = "marketing_template"


class SenderUnavailable(TransactionalEmailError):
    code = "sender_unavailable"


class InvalidRecipient(TransactionalEmailError):
    code = "invalid_recipient"


class QuotaLimited(TransactionalEmailError):
    code = "quota_limited"


class SendInProgress(TransactionalEmailError):
    code = "idempotency_conflict"


class IdempotencyKeyReused(TransactionalEmailError):
    code = "idempotency_key_reused"


class DeliveryUnavailable(Exception):
    """The email pipeline did not accept the send. Safe to retry."""


@frozen
class QueuedEmail:
    message_id: str
    # True when an earlier request with the same idempotency key already queued this email.
    replayed: bool
