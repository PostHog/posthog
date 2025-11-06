from django.utils import timezone

import structlog
from celery import shared_task
from prometheus_client import Counter

from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.tasks.utils import CeleryQueue

from products.enterprise.backend.session_recordings.session_recording_extensions import (
    MAXIMUM_AGE_FOR_RECORDING_V2,
    MINIMUM_AGE_FOR_RECORDING,
    persist_recording_v2,
)

logger = structlog.get_logger(__name__)

REPLAY_NEEDS_PERSISTENCE_COUNTER = Counter(
    "snapshot_persist_persistence_task_queued",
    "Count of session recordings that need to be persisted",
    # we normally avoid team label but not all teams pin recordings, so there shouldn't be _too_ many labels here
    labelnames=["team_id"],
)

REPLAY_NEEDS_PERSISTENCE_V2_COUNTER = Counter(
    "snapshot_persist_persistence_task_queued_v2",
    "Count of v2 session recordings that need to be persisted",
    labelnames=["team_id"],
)


@shared_task(ignore_result=True, queue=CeleryQueue.SESSION_REPLAY_PERSISTENCE.value, rate_limit="30/m")
def persist_single_recording_v2(id: str, team_id: int) -> None:
    persist_recording_v2(id, team_id)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.SESSION_REPLAY_PERSISTENCE.value,
)
def persist_finished_recordings_v2() -> None:
    now = timezone.now()
    max_created_at = now - MINIMUM_AGE_FOR_RECORDING
    min_created_at = now - MAXIMUM_AGE_FOR_RECORDING_V2

    finished_recordings = SessionRecording.objects.filter(
        created_at__lte=max_created_at, created_at__gte=min_created_at, full_recording_v2_path=None
    )

    logger.info("Persisting v2 finished recordings", count=finished_recordings.count())

    for recording in finished_recordings:
        REPLAY_NEEDS_PERSISTENCE_V2_COUNTER.labels(team_id=recording.team_id).inc()
        persist_single_recording_v2.delay(recording.session_id, recording.team_id)
