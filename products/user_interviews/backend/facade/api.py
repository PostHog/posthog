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

from typing import Any
from uuid import UUID

from posthog.ingress.contracts import WebhookDelivery
from posthog.models.sharing_configuration import SharingConfiguration

from products.user_interviews.backend import logic
from products.user_interviews.backend.classification import derive_auto_classifications
from products.user_interviews.backend.facade.contracts import IntervieweeIdentity

__all__ = [
    "RESPONDENT_KEY_MAX_CHARS",
    "RESPONDENT_NAME_MAX_CHARS",
    "SHARED_INTERVIEWEE_IDENTIFIER",
    "IntervieweeIdentity",
    "accept_vapi_event",
    "clean_field",
    "derive_auto_classifications",
    "has_replied",
    "is_shared_interviewee_context",
    "parse_interviewee_identifier",
    "resolve_share",
    "shared_interviewee_identifier",
    "valid_distinct_id",
    "valid_session_id",
]

SHARED_INTERVIEWEE_IDENTIFIER = logic.SHARED_INTERVIEWEE_IDENTIFIER
RESPONDENT_NAME_MAX_CHARS = logic.RESPONDENT_NAME_MAX_CHARS
RESPONDENT_KEY_MAX_CHARS = logic.RESPONDENT_KEY_MAX_CHARS


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


def clean_field(value: Any, max_chars: int) -> str:
    return logic.clean_field(value, max_chars)


def shared_interviewee_identifier(respondent_key: str) -> str:
    return logic.shared_interviewee_identifier(respondent_key)


def resolve_share(access_token: str) -> SharingConfiguration | None:
    # Hands back the core sharing row rather than a contract, because `start_call` reads the whole
    # interviewee-context/topic graph off it. Narrowing it means converting that view first.
    return logic.resolve_share(access_token)


def accept_vapi_event(delivery: WebhookDelivery) -> None:
    # Deferred: keeps the embedding worker and the analytics client off the facade import path.
    from products.user_interviews.backend import vapi_events  # noqa: PLC0415

    vapi_events.handle_vapi_webhook_delivery(delivery)
