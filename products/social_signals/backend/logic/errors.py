"""Domain exceptions for social_signals. Imported through the facade."""


class MentionSourceNotFoundError(LookupError):
    """A MentionSource lookup (by id or token) returned no row."""


class MentionNotFoundError(LookupError):
    """A Mention lookup returned no row."""


class UnknownAdapterError(LookupError):
    """No WebhookAdapter is registered for the requested source kind."""
