"""
Facade API for user_interviews.

This is the ONLY module other apps are allowed to import.

Responsibilities:
- Accept primitives / contracts as input
- Call domain logic / ORM
- Return contracts (no ORM instances)
- Remain thin and stable

Do NOT:
- Import DRF, serializers, or HTTP concerns
- Return ORM instances or QuerySets
"""

import re
from uuid import UUID

from products.user_interviews.backend.facade.contracts import IntervieweeIdentity
from products.user_interviews.backend.models import EmailWithDisplayNameValidator, UserInterview


def parse_interviewee_identifier(identifier: str) -> IntervieweeIdentity:
    """Split an interviewee identifier into a display name and (optional) email.

    Accepts the same display-name format the topic validator accepts —
    ``"Display Name <email@host>"`` — falling back to a best-effort
    title-cased local-part for raw emails and the identifier as-is for
    distinct IDs.
    """
    identifier = identifier.strip()
    display_match = re.match(EmailWithDisplayNameValidator.display_name_regex, identifier)
    if display_match:
        return IntervieweeIdentity(
            display_name=display_match.group(1).strip(),
            email=display_match.group(2).strip(),
        )
    if "@" in identifier:
        local_part = identifier.split("@", 1)[0]
        return IntervieweeIdentity(
            display_name=local_part.replace(".", " ").replace("_", " ").strip().title() or identifier,
            email=identifier,
        )
    return IntervieweeIdentity(display_name=identifier, email=None)


def has_replied(*, team_id: int, topic_id: UUID, interviewee_identifier: str) -> bool:
    """Whether an interviewee has already completed an interview for this topic."""
    return UserInterview.objects.filter(
        team_id=team_id,
        topic_id=topic_id,
        interviewee_identifier=interviewee_identifier,
    ).exists()
