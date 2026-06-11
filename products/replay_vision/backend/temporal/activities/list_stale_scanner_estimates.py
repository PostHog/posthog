from django.db.models import F, Q
from django.utils import timezone

from temporalio import activity

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.queries import ESTIMATE_STALE_AFTER
from products.replay_vision.backend.temporal.constants import ESTIMATES_MAX_PER_RUN
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.estimates_types import RefreshScannerEstimateInputs


@activity.defn
@track_activity()
def list_stale_scanner_estimates_activity() -> list[RefreshScannerEstimateInputs]:
    """Enabled scanners whose persisted estimate is missing or past the staleness window, oldest first."""
    cutoff = timezone.now() - ESTIMATE_STALE_AFTER
    rows = (
        ReplayScanner.objects.filter(enabled=True)
        .filter(Q(estimated_at__isnull=True) | Q(estimated_at__lt=cutoff))
        # Never-estimated scanners first, then the longest-stale, so a backlog drains fairly across runs.
        .order_by(F("estimated_at").asc(nulls_first=True))
        .values_list("id", "team_id")[:ESTIMATES_MAX_PER_RUN]
    )
    return [RefreshScannerEstimateInputs(scanner_id=scanner_id, team_id=team_id) for scanner_id, team_id in rows]
