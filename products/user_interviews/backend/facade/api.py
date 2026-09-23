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

import structlog

from posthog.ingress.contracts import WebhookDelivery

from products.user_interviews.backend import logic
from products.user_interviews.backend.classification import derive_auto_classifications
from products.user_interviews.backend.facade.contracts import IntervieweeIdentity

logger = structlog.get_logger(__name__)

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
    """Resolve the share this delivery belongs to, and hand the work to a queue.

    The token is resolved here, in the request, because the answer expires: a share that the
    team disables, or a token that leaves its rotation grace period, while the work waits in
    the queue would make the worker find nothing and drop a report the endpoint has already
    accepted. So does the share row itself, which the cleanup command deletes once the token is
    past its grace period. What crosses the broker is the team, the topic and the interviewee
    context the share names, and nothing removes those with the share.

    A token nothing answers enqueues nothing. ingress ignores what a consumer returns, so there
    is no status to refuse the delivery with, and queueing work for a share nobody can name only
    moves the dead end into a worker. A database failure raises instead, which costs the request
    its receipt and makes Vapi send the report again.
    """
    # Deferred: keeps the Celery app off the facade import path.
    from products.user_interviews.backend.tasks.tasks import handle_vapi_webhook  # noqa: PLC0415

    call_id = delivery.context.get("call_id")
    access_token = logic.vapi_access_token(delivery.payload)
    if not access_token:
        logger.warning(
            "user_interviews_vapi_webhook_missing_access_token",
            event_type=delivery.event_type,
            call_id=call_id,
        )
        return

    share = logic.vapi_share_identity(access_token)
    if share is None:
        logger.warning(
            "user_interviews_vapi_webhook_unknown_access_token",
            event_type=delivery.event_type,
            call_id=call_id,
        )
        return

    handle_vapi_webhook.delay(
        payload=dict(delivery.payload),
        event_type=delivery.event_type,
        team_id=share.team_id,
        topic_id=share.topic_id,
        interviewee_context_id=share.interviewee_context_id,
        interviewee_identifier=share.interviewee_identifier,
        # The lifecycle analytics events are timestamped with this, not with the moment the worker
        # runs, so a delayed or retried task cannot report a call as started after it ended. Sent
        # as a string because the broker carries JSON, which has no datetime.
        received_at=delivery.received_at.isoformat(),
    )
