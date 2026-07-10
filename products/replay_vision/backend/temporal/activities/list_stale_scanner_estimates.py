from django.db.models import F, Q
from django.utils import timezone

from temporalio import activity

from posthog.temporal.common.utils import close_db_connections

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.queries import ESTIMATE_STALE_AFTER
from products.replay_vision.backend.temporal.constants import ESTIMATES_MAX_PER_RUN
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.estimates_types import RefreshScannerEstimateInputs


@activity.defn
@close_db_connections
@track_activity()
def list_stale_scanner_estimates_activity() -> list[RefreshScannerEstimateInputs]:
    """Scanners whose persisted estimate is missing or past the staleness window.

    Disabled scanners are refreshed too so re-enabling one puts an accurate number straight into the
    quota sum. Enabled scanners come first so they can't starve behind a backlog of disabled ones.
    """
    cutoff = timezone.now() - ESTIMATE_STALE_AFTER
    rows = (
        ReplayScanner.objects.filter(Q(estimated_at__isnull=True) | Q(estimated_at__lt=cutoff))
        .order_by("-enabled", F("estimated_at").asc(nulls_first=True))
        .values_list("id", "team_id")[:ESTIMATES_MAX_PER_RUN]
    )
    return [RefreshScannerEstimateInputs(scanner_id=scanner_id, team_id=team_id) for scanner_id, team_id in rows]
