from django.utils import timezone

from rest_framework.exceptions import (
    PermissionDenied,
    ValidationError as DRFValidationError,
)
from temporalio import activity

from posthog.clickhouse.client.connection import ClickHouseUser

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.queries import (
    ESTIMATE_STALE_AFTER,
    is_experiment_linkage_unresolved,
    refresh_scanner_estimate,
)
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.estimates_types import RefreshScannerEstimateInputs
from products.replay_vision.backend.temporal.metrics import record_estimate_outcome


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
    except (DRFValidationError, PermissionDenied) as error:
        if not is_experiment_linkage_unresolved(scanner, error):
            # The scanner's own query no longer builds, for example a deleted action or a bad
            # cohort reference. No launch heals that, so let the activity fail: the failure
            # metric and the workflow's partial-failure warning keep it alertable.
            raise
        # The experiment targeting cannot resolve an exposed population. A draft heals itself at
        # launch; the other states need a person. The sweep skips its tick on the same set.
        # `refresh_scanner_estimate` stamps `estimate_attempted_at` before it queries, so the
        # one-hour backoff still applies.
        record_estimate_outcome("experiment_linkage_unresolved")
        activity.logger.warning(
            "replay_vision.estimate_linkage_unresolved",
            extra={"scanner_id": str(scanner.id), "reason": error.detail},
        )
        return False
    record_estimate_outcome("refreshed")
    return True
