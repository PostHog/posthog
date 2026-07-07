"""Parsing and user resolution for @-mention tokens embedded in thread message content.

Mentions are stored inline as ``@[Display Name](email)`` (the canonical format
shared with PostHog Code clients), so any layer can answer "who does this
message mention?" from the plain string alone.
"""

import re
from typing import Any

from django.db.models.functions import Lower

MENTION_TOKEN_PATTERN = re.compile(r"@\[[^\][\n]+\]\(([^\s()]+@[^\s()]+)\)")

# Content length is unbounded, so cap how many distinct emails one message may
# resolve to keep the lookup's IN list from growing with attacker-sized input.
MAX_RESOLVED_MENTIONS_PER_MESSAGE = 50


def extract_mention_emails(content: str) -> set[str]:
    """Emails mentioned in the content, lowercased and deduped."""
    return {match.group(1).lower() for match in MENTION_TOKEN_PATTERN.finditer(content)}


def resolve_mentioned_user_ids(user_model: Any, content: str, *, team_id: int, author_id: int | None) -> list[int]:
    """Ids of the team's org members mentioned in the content, excluding the author.

    Emails resolve case-insensitively and only to members of the team's organization.
    ``user_model`` is injected so the backfill migration can pass its historical model
    and stay filter-identical with the write path.
    """
    emails = sorted(extract_mention_emails(content))[:MAX_RESOLVED_MENTIONS_PER_MESSAGE]
    if not emails:
        return []
    member_ids = (
        user_model.objects.annotate(_email_lower=Lower("email"))
        .filter(organizations__team__id=team_id, _email_lower__in=emails)
        .values_list("id", flat=True)
        .distinct()
    )
    return [user_id for user_id in member_ids if user_id != author_id]
