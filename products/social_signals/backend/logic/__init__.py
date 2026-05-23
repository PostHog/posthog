"""Domain logic for social_signals.

Only the facade may import from this package. Presentation layer must go
through ``facade.api`` (enforced by import-linter).
"""

from .errors import (
    MentionNotFoundError,
    MentionSourceNotFoundError,
    UnknownAdapterError,
)

__all__ = [
    "MentionNotFoundError",
    "MentionSourceNotFoundError",
    "UnknownAdapterError",
]
