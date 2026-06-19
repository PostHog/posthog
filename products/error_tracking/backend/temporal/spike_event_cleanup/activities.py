import datetime

from django.db import close_old_connections
from django.utils import timezone

import structlog
from temporalio import activity

from products.error_tracking.backend.models import ErrorTrackingSpikeEvent
from products.error_tracking.backend.temporal.spike_event_cleanup.types import (
    SpikeEventCleanupInputs,
    SpikeEventCleanupResult,
)

logger = structlog.get_logger(__name__)


@activity.defn
def cleanup_spike_events_activity(inputs: SpikeEventCleanupInputs) -> SpikeEventCleanupResult:
    close_old_connections()

    cutoff = timezone.now() - datetime.timedelta(days=inputs.days_old)
    deleted_count, _ = ErrorTrackingSpikeEvent.objects.filter(detected_at__lt=cutoff).delete()
    logger.info(
        "error_tracking.spike_event_cleanup.complete",
        deleted_count=deleted_count,
        cutoff=cutoff.isoformat(),
    )

    return SpikeEventCleanupResult(deleted_count=deleted_count)
