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

from uuid import UUID

from products.user_interviews.backend import logic
from products.user_interviews.backend.classification import derive_auto_classifications
from products.user_interviews.backend.facade.contracts import IntervieweeIdentity

__all__ = [
    "IntervieweeIdentity",
    "derive_auto_classifications",
    "has_replied",
    "parse_interviewee_identifier",
]


def parse_interviewee_identifier(identifier: str) -> IntervieweeIdentity:
    return logic.parse_interviewee_identifier(identifier)


def has_replied(*, team_id: int, topic_id: UUID, interviewee_identifier: str) -> bool:
    return logic.has_replied(
        team_id=team_id,
        topic_id=topic_id,
        interviewee_identifier=interviewee_identifier,
    )
