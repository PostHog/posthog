from django.db.models import F, Q
from django.utils import timezone

from temporalio import activity

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.queries import DISABLED_ESTIMATE_STALE_AFTER, ESTIMATE_STALE_AFTER
from products.replay_vision.backend.temporal.constants import ESTIMATES_MAX_PER_RUN
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.estimates_types import RefreshScannerEstimateInputs


@activity.defn
@track_activity()
def list_stale_scanner_estimates_activity() -> list[RefreshScannerEstimateInputs]:
    """Scanners whose persisted estimate is missing or past the staleness window.

    Disabled scanners are refreshed too, on a slower clock, so re-enabling one still puts a usable
    number into the quota sum. Enabled scanners come first so they can't starve behind a backlog of
    disabled ones.
    """
    now = timezone.now()
    stale = (
        Q(estimated_at__isnull=True)
        | Q(enabled=True, estimated_at__lt=now - ESTIMATE_STALE_AFTER)
        | Q(enabled=False, estimated_at__lt=now - DISABLED_ESTIMATE_STALE_AFTER)
    )
    rows = (
        ReplayScanner.objects.filter(stale)
        .order_by("-enabled", F("estimated_at").asc(nulls_first=True))
        .values_list("id", "team_id")[:ESTIMATES_MAX_PER_RUN]
    )
    return [RefreshScannerEstimateInputs(scanner_id=scanner_id, team_id=team_id) for scanner_id, team_id in rows]
