"""
Facade API for user_interviews.

The primary facade module for data capabilities. Other facade submodules
(max_tools.py) expose wiring; external code must import only from backend/facade/.

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

from posthog.ingress.contracts import WebhookDelivery

from products.user_interviews.backend import logic
from products.user_interviews.backend.classification import derive_auto_classifications
from products.user_interviews.backend.facade.contracts import IntervieweeIdentity

__all__ = [
    "SHARED_INTERVIEWEE_IDENTIFIER",
    "IntervieweeIdentity",
    "accept_vapi_event",
    "derive_auto_classifications",
    "has_replied",
    "is_shared_interviewee_context",
    "parse_interviewee_identifier",
    "valid_distinct_id",
    "valid_session_id",
]

SHARED_INTERVIEWEE_IDENTIFIER = logic.SHARED_INTERVIEWEE_IDENTIFIER


def is_shared_interviewee_context(interviewee_identifier: str) -> bool:
    return logic.is_shared_interviewee_context(interviewee_identifier)


def valid_distinct_id(value: object) -> str:
    return logic.valid_distinct_id(value)


def valid_session_id(value: object) -> str:
    return logic.valid_session_id(value)


def parse_interviewee_identifier(identifier: str) -> IntervieweeIdentity:
    return logic.parse_interviewee_identifier(identifier)


def has_replied(*, team_id: int, topic_id: UUID, interviewee_identifier: str) -> bool:
    return logic.has_replied(
        team_id=team_id,
        topic_id=topic_id,
        interviewee_identifier=interviewee_identifier,
    )


def accept_vapi_event(delivery: WebhookDelivery) -> None:
    # Deferred: keeps the embedding worker and the analytics client off the facade import path.
    from products.user_interviews.backend import vapi_events  # noqa: PLC0415

    vapi_events.handle_vapi_webhook_delivery(delivery)
