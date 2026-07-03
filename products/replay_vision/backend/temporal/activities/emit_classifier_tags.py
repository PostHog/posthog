"""Side-effect: write classifier output as `ai_tags_fixed` / `ai_tags_freeform` on the session_replay_events row.

Reads the recorded session's distinct_id + start_time (persisted on the observation by `fetch_session_events`),
then produces a Kafka message to `KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS` with identity values for every non-tagging
column so the SimpleAggregateFunction merge doesn't poison the existing session row. Any failure surfaces and fails
the observation.
"""

from datetime import datetime, timedelta
from uuid import UUID

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.kafka_client.routing import producer_scope
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.sync import database_sync_to_async

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.temporal.constants import KAFKA_DELIVERY_TIMEOUT_S
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.types import EmitClassifierTagsInputs

logger = structlog.get_logger(__name__)


def _load_session_identity(observation_id: UUID) -> tuple[str | None, datetime | None] | None:
    return ReplayObservation.objects.filter(pk=observation_id).values_list("distinct_id", "session_started_at").first()


@activity.defn
@track_activity()
async def emit_classifier_tags_activity(inputs: EmitClassifierTagsInputs) -> None:
    """Merge classifier tags into the session row via Kafka. Raises on failure."""
    # distinct_id + start_time were persisted by `fetch_session_events`, so reuse them instead of re-querying CH.
    identity = await database_sync_to_async(_load_session_identity)(inputs.observation_id)
    if identity is None or identity[1] is None:
        raise ApplicationError(
            f"No persisted session metadata for observation {inputs.observation_id} (session {inputs.session_id})",
            non_retryable=True,
        )
    distinct_id = identity[0] or ""
    session_start = identity[1]
    # Microsecond offset keeps min/max/argMin/argMax aggregates on the existing real values.
    tag_row_ts = format_clickhouse_timestamp(session_start + timedelta(microseconds=1))
    payload = {
        "session_id": inputs.session_id,
        "team_id": inputs.team_id,
        "distinct_id": distinct_id,
        "first_timestamp": tag_row_ts,
        "last_timestamp": tag_row_ts,
        "block_url": None,
        "first_url": None,
        "urls": [],
        "click_count": 0,
        "keypress_count": 0,
        "mouse_activity_count": 0,
        "active_milliseconds": 0,
        "console_log_count": 0,
        "console_warn_count": 0,
        "console_error_count": 0,
        "size": 0,
        "event_count": 0,
        "message_count": 0,
        "snapshot_source": None,
        "snapshot_library": None,
        "retention_period_days": None,
        "is_deleted": 0,
        "ai_tags_fixed": list(inputs.classifier_output.tags),
        "ai_tags_freeform": list(inputs.classifier_output.tags_freeform),
    }

    def emit() -> None:
        with producer_scope(
            topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS, flush_timeout=KAFKA_DELIVERY_TIMEOUT_S
        ) as producer:
            result = producer.produce(topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS, data=payload)
        result.get(timeout=0)

    await sync_to_async(emit, thread_sensitive=False)()
    logger.debug(
        "replay_vision.emit_classifier_tags.produced",
        session_id=inputs.session_id,
        observation_id=str(inputs.observation_id),
        tags_fixed=payload["ai_tags_fixed"],
        tags_freeform=payload["ai_tags_freeform"],
    )


__all__ = ["emit_classifier_tags_activity"]
