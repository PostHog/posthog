import structlog
from prometheus_client import Counter
from temporalio import activity

from posthog.event_usage import groups
from posthog.models import Team
from posthog.ph_client import ph_scoped_capture
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.utils import close_stale_db_connections

# A module import: the sweep reaches this package through lifecycle_events, so the cycle resolves
# only when the names are read at call time.
from products.error_tracking.backend.logic import auto_resolve_sweep
from products.error_tracking.backend.temporal.auto_resolve.types import (
    AutoResolveInputs,
    AutoResolveTeamsInputs,
    AutoResolveTeamsResult,
)

logger = structlog.get_logger(__name__)

ISSUES_AUTO_RESOLVED = Counter(
    "error_tracking_issues_auto_resolved_total",
    "Issues the daily auto-resolve run resolved",
)

# pinned: analytics event name - renaming breaks dashboards
ISSUES_AUTO_RESOLVED_EVENT = "error tracking issues auto resolved"


@activity.defn
def get_auto_resolve_team_batches_activity(inputs: AutoResolveInputs) -> list[list[int]]:
    close_stale_db_connections()
    team_ids = auto_resolve_sweep.auto_resolve_team_ids()
    logger.info("error_tracking.auto_resolve.teams_selected", team_count=len(team_ids))
    return [team_ids[start : start + inputs.batch_size] for start in range(0, len(team_ids), inputs.batch_size)]


@activity.defn
def auto_resolve_teams_activity(inputs: AutoResolveTeamsInputs) -> AutoResolveTeamsResult:
    close_stale_db_connections()
    teams_processed = 0
    teams_failed = 0
    issues_resolved = 0
    # One team's sweep can outlast the heartbeat timeout, so a background thread sends the heartbeats.
    with ph_scoped_capture() as capture, HeartbeaterSync(logger=logger):
        for team_id in inputs.team_ids:
            try:
                run = auto_resolve_sweep.auto_resolve_team(team_id)
            except Exception:
                teams_failed += 1
                logger.exception("error_tracking.auto_resolve.team_failed", team_id=team_id)
                continue
            if run is None:
                continue
            teams_processed += 1
            issues_resolved += run.resolved_count
            ISSUES_AUTO_RESOLVED.inc(run.resolved_count)
            team = Team.objects.get(id=team_id)
            capture(
                distinct_id=str(team.uuid),
                event=ISSUES_AUTO_RESOLVED_EVENT,
                groups=groups(team=team),
                properties={"resolved_count": run.resolved_count, "after_days": run.after_days},
            )
    return AutoResolveTeamsResult(
        teams_processed=teams_processed, teams_failed=teams_failed, issues_resolved=issues_resolved
    )
