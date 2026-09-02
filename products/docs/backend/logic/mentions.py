"""The people a post names: ``@[Name](email)`` tokens, as the desktop composer writes them."""

import re

from django.db.models.functions import Lower

from posthog.models.team import Team
from posthog.models.user import User

_MENTION = re.compile(r"@\[[^\]]*\]\(([^)\s]+)\)")


def mentioned_emails(content: str) -> list[str]:
    """Every email a post names, once each, in order, lower-cased."""
    seen: list[str] = []
    for email in _MENTION.findall(content or ""):
        lowered = email.strip().lower()
        if lowered and lowered not in seen:
            seen.append(lowered)
    return seen


def mentioned_user_ids(team: Team, content: str) -> list[int]:
    """The members of the team's organization a post names. Others are words, not people."""
    emails = mentioned_emails(content)
    if not emails:
        return []
    members = (
        User.objects.annotate(lower_email=Lower("email"))
        .filter(organization_membership__organization_id=team.organization_id, lower_email__in=emails)
        .values_list("id", "lower_email")
    )
    by_email = {email: user_id for user_id, email in members}
    return [by_email[email] for email in emails if email in by_email]
