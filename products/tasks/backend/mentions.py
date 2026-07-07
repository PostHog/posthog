"""Parsing for @-mention tokens embedded in thread message content.

Mentions are stored inline as ``@[Display Name](email)`` (the canonical format
shared with PostHog Code clients), so any layer can answer "who does this
message mention?" from the plain string alone.
"""

import re

MENTION_TOKEN_PATTERN = re.compile(r"@\[[^\][\n]+\]\(([^\s()]+@[^\s()]+)\)")


def extract_mention_emails(content: str) -> set[str]:
    """Emails mentioned in the content, lowercased and deduped."""
    return {match.group(1).lower() for match in MENTION_TOKEN_PATTERN.finditer(content)}
