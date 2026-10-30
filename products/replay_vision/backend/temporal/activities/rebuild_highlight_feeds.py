import time

from temporalio import activity

from products.replay_vision.backend.highlight_builds import rebuild_changed_feeds
from products.replay_vision.backend.temporal.constants import HIGHLIGHT_REBUILD_ACTIVITY_TIMEOUT
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.highlight_rebuild_types import RebuildHighlightFeedsResult
from products.replay_vision.backend.temporal.query_budget import bounded_queries
from products.replay_vision.backend.watch_rank import ANCHOR_VERSION


@activity.defn
@track_activity()
def rebuild_highlight_feeds_activity() -> RebuildHighlightFeedsResult:
    """Rebuild every team whose ranks changed since its last build, a batch at a time, until none is due or the claim
    budget runs out."""
    built = 0
    # Stops before the next team once the budget runs out, and cancels a build's queries that run past it.
    with bounded_queries(HIGHLIGHT_REBUILD_ACTIVITY_TIMEOUT) as deadline:

        def before_team() -> bool:
            activity.heartbeat()
            return time.time() < deadline

        while time.time() < deadline:
            batch = rebuild_changed_feeds(ANCHOR_VERSION, on_team=before_team)
            if not batch:
                break
            built += batch
    return RebuildHighlightFeedsResult(built=built)
