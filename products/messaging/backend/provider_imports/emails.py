"""Email address checks that every provider import shares."""

from typing import Any

from posthog.helpers.email_utils import email_domain

MAX_EMAIL_LENGTH = 512


def normalized_email(value: Any) -> str | None:
    """The address lowercased, the way suppressions store it, or None when it isn't a usable address."""
    if not isinstance(value, str):
        return None
    # Postgres can't store a NUL byte in a text column.
    email = value.replace("\x00", "").strip().lower()
    return email if email_domain(email) and not email.startswith("@") and len(email) <= MAX_EMAIL_LENGTH else None


def exact_email(value: Any) -> str | None:
    """The address with its case kept, because an opt-out matches the address a send names exactly."""
    return value.replace("\x00", "").strip() if normalized_email(value) else None
