"""Re-emits `$recording_observed` events for succeeded observations whose event never reached ClickHouse.

The apply workflow emits this event fail-soft *after* the observation is already persisted and billed, so a
capture that exhausts its retries (or a worker that dies between mark-succeeded and emit) leaves a succeeded
Postgres row with no matching event. The Postgres-backed stats then show data the ClickHouse-backed charts
don't. This reconcile closes that gap; the emit is dedup-keyed on the observation id, so re-emitting a row
that actually did land is harmless.
"""

from datetime import UTC, datetime

import structlog
from temporalio import activity

from posthog.sync import database_sync_to_async

from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.temporal.activities.emit_observation_event import emit_observation_event
from products.replay_vision.backend.temporal.constants import (
    OBSERVATION_EVENT_BACKFILL_BATCH_SIZE,
    OBSERVATION_EVENT_BACKFILL_GRACE,
)
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.types import ScannerResult

logger = structlog.get_logger(__name__)


def _backfill_events() -> int:
    cutoff = datetime.now(UTC) - OBSERVATION_EVENT_BACKFILL_GRACE
    observations = list(
        ReplayObservation.objects.select_related("team")
        .filter(status=ObservationStatus.SUCCEEDED, event_emitted_at__isnull=True, completed_at__lt=cutoff)
        .order_by("completed_at")[:OBSERVATION_EVENT_BACKFILL_BATCH_SIZE]
    )
    if not observations:
        return 0

    emitted = 0
    skipped_bad_result = 0
    failed = 0
    for observation in observations:
        try:
            model_output = ScannerResult.model_validate(observation.scanner_result).model_output
        except Exception:
            # A malformed result won't parse on any retry, so don't let it wedge the sweep — skip it.
            skipped_bad_result += 1
            continue
        try:
            emit_observation_event(observation, model_output)
            emitted += 1
        except Exception:
            # Transient (e.g. capture at capacity); the next tick retries this row.
            failed += 1
            logger.exception("replay_vision.backfill_observation_event_failed", observation_id=str(observation.id))

    logger.info(
        "replay_vision.backfill_observation_events",
        scanned=len(observations),
        emitted=emitted,
        skipped_bad_result=skipped_bad_result,
        failed=failed,
    )
    return emitted


@activity.defn
@track_activity()
async def backfill_observation_events_activity() -> int:
    """Emit missing `$recording_observed` events for succeeded observations; returns the count emitted."""
    return await database_sync_to_async(_backfill_events, thread_sensitive=False)()
