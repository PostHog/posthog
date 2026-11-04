"""Mask credential-shaped substrings in report text.

A person can paste a token into a report and then edit it out. The edit history keeps the text
before and after each edit, so it must not keep the token. Matching on token shapes needs no
access to the live values.
"""

import re

from posthog.models.utils import (
    OAUTH_ACCESS_TOKEN_PREFIX,
    OAUTH_REFRESH_TOKEN_PREFIX,
    PERSONAL_API_KEY_PREFIX,
    SECRET_API_TOKEN_PREFIX,
)

REDACTED = "[redacted]"

# Project API tokens (`phc_`) are public by design and stay out of this list.
_POSTHOG_SECRET_PREFIXES = (
    PERSONAL_API_KEY_PREFIX,
    SECRET_API_TOKEN_PREFIX,
    OAUTH_ACCESS_TOKEN_PREFIX,
    OAUTH_REFRESH_TOKEN_PREFIX,
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:" + "|".join(re.escape(p) for p in _POSTHOG_SECRET_PREFIXES) + r")[A-Za-z0-9]{16,}\b"),
    # GitHub tokens: installation (ghs), classic PAT (ghp), OAuth (gho), user-to-server (ghu), refresh (ghr).
    re.compile(r"\bgh[psour]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    # Credentials in a URL, such as `https://x-access-token:<token>@github.com/`.
    re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),
)


def redact_credentials(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text
