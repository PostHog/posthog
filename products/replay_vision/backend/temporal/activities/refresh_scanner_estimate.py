from django.utils import timezone

from rest_framework.exceptions import (
    PermissionDenied,
    ValidationError as DRFValidationError,
)
from temporalio import activity

from posthog.clickhouse.client.connection import ClickHouseUser

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.queries import ESTIMATE_STALE_AFTER, refresh_scanner_estimate
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.estimates_types import RefreshScannerEstimateInputs


@activity.defn
@track_activity()
def refresh_scanner_estimate_activity(inputs: RefreshScannerEstimateInputs) -> bool:
    """Recompute the scanner's persisted estimate; the staleness re-check makes it idempotent against an interactive save racing the batch."""
    scanner = ReplayScanner.objects.filter(pk=inputs.scanner_id, team_id=inputs.team_id).select_related("team").first()
    if scanner is None:
        return False
    if scanner.estimated_at is not None and timezone.now() - scanner.estimated_at < ESTIMATE_STALE_AFTER:
        return False
    try:
        refresh_scanner_estimate(scanner, ch_user=ClickHouseUser.REPLAY_VISION)
    except (DRFValidationError, PermissionDenied):
        # The targeted experiment gives the estimate no population to count: a draft, deleted, or
        # group-aggregated experiment, or a creator who lost experiment access. The sweep skips the
        # same states. `refresh_scanner_estimate` stamps `estimate_attempted_at` before it queries,
        # so the one-hour backoff still applies and the scanner does not count as a failed activity.
        return False
    return True
