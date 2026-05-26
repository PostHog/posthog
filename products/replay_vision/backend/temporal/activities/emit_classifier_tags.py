"""Side-effect: write classifier output as `ai_tags_fixed` / `ai_tags_freeform` on the session_replay_events row.

Fetches session metadata (distinct_id + start_time), then produces a Kafka message to
`KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS` with identity values for every non-tagging column so the
SimpleAggregateFunction merge doesn't poison the existing session row. Any failure surfaces and fails the observation.
"""

from datetime import timedelta

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.kafka_client.routing import producer_scope
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS
from posthog.models import Team
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.sync import database_sync_to_async

from products.replay_vision.backend.temporal.types import EmitClassifierTagsInputs

logger = structlog.get_logger(__name__)

# Bounded so broker errors surface as activity failures instead of getting lost in the producer buffer.
_KAFKA_DELIVERY_TIMEOUT_S = 10.0


@activity.defn
async def emit_classifier_tags_activity(inputs: EmitClassifierTagsInputs) -> None:
    """Merge classifier tags into the session row via Kafka. Raises on failure."""
    # `get_metadata` only reads `team.pk`, so a stub instance avoids the extra DB roundtrip.
    team = Team(pk=inputs.team_id)
    metadata = await database_sync_to_async(SessionReplayEvents().get_metadata)(session_id=inputs.session_id, team=team)
    if metadata is None:
        raise ApplicationError(
            f"No replay metadata for session {inputs.session_id} (team {inputs.team_id})", non_retryable=True
        )
    distinct_id = metadata.get("distinct_id") or ""
    session_start = metadata["start_time"]
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
            topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS, flush_timeout=_KAFKA_DELIVERY_TIMEOUT_S
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
