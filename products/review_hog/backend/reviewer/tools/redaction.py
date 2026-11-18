"""Scrub credential shapes out of agent-authored text before it reaches GitHub.

The resolution sandbox holds a GitHub installation token and a PostHog personal API key, and its
git remote carries the token inline, so command output an agent pastes into a verdict can contain
a live credential. Matching on token shapes needs no access to the live values, which the delivery
step does not have.
"""

import re

from posthog.models.utils import (
    OAUTH_ACCESS_TOKEN_PREFIX,
    OAUTH_REFRESH_TOKEN_PREFIX,
    PERSONAL_API_KEY_PREFIX,
    SECRET_API_TOKEN_PREFIX,
)

REDACTED = "[redacted]"

# Per-run AI gateway token the sandbox receives as AI_GATEWAY_TOKEN (minted in
# products/tasks/backend/temporal/process_task/ai_gateway_token.py, which has no prefix constant).
_AI_GATEWAY_TOKEN_PREFIX = "phe_"

# Project API tokens (`phc_`) are public by design and stay out of this list.
_POSTHOG_SECRET_PREFIXES = (
    PERSONAL_API_KEY_PREFIX,
    SECRET_API_TOKEN_PREFIX,
    OAUTH_ACCESS_TOKEN_PREFIX,
    OAUTH_REFRESH_TOKEN_PREFIX,
    _AI_GATEWAY_TOKEN_PREFIX,
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:" + "|".join(re.escape(p) for p in _POSTHOG_SECRET_PREFIXES) + r")[A-Za-z0-9]{16,}\b"),
    # GitHub tokens: installation (ghs), classic PAT (ghp), OAuth (gho), user-to-server (ghu), refresh (ghr).
    re.compile(r"\bgh[psour]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
)

_CLONE_URL_TOKEN = re.compile(r"(?P<prefix>https://x-access-token:)[^@\s]+(?P<suffix>@github\.com/)")


def redact_secrets(text: str) -> tuple[str, int]:
    """Replace every credential-shaped substring with `[redacted]`; returns the text and the match count."""
    # The clone URL goes first so the token inside it counts once, not again as a bare token shape.
    text, total = _CLONE_URL_TOKEN.subn(rf"\g<prefix>{REDACTED}\g<suffix>", text)
    for pattern in _SECRET_PATTERNS:
        text, count = pattern.subn(REDACTED, text)
        total += count
    return text, total
