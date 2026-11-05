import time

from temporalio import activity

from products.replay_vision.backend.highlight_builds import rebuild_changed_feeds
from products.replay_vision.backend.temporal.constants import HIGHLIGHT_REBUILD_CLAIM_BUDGET
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.highlight_rebuild_types import RebuildHighlightFeedsResult
from products.replay_vision.backend.watch_rank import ANCHOR_VERSION


@activity.defn
@track_activity()
def rebuild_highlight_feeds_activity() -> RebuildHighlightFeedsResult:
    """Rebuild every team whose ranks changed since its last build, a batch at a time, until none is due or the claim
    budget runs out."""
    # Not `bounded_queries`: it would lift each build's own 120s statement cap to the whole budget.
    deadline = time.monotonic() + HIGHLIGHT_REBUILD_CLAIM_BUDGET.total_seconds()

    def before_team() -> bool:
        activity.heartbeat()
        return time.monotonic() < deadline

    built = 0
    while time.monotonic() < deadline:
        batch = rebuild_changed_feeds(ANCHOR_VERSION, on_team=before_team)
        if not batch:
            break
        built += batch
    return RebuildHighlightFeedsResult(built=built)
