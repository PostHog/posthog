from django.utils import timezone

from temporalio import activity

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
    refresh_scanner_estimate(scanner)
    return True
