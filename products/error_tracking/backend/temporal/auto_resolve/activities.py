import structlog
from temporalio import activity

from posthog.temporal.common.utils import close_db_connections

from products.error_tracking.backend.logic import auto_resolve

logger = structlog.get_logger(__name__)


@activity.defn
@close_db_connections
def list_auto_resolve_teams() -> list[int]:
    return auto_resolve.auto_resolve_team_ids()


@activity.defn
@close_db_connections
def resolve_quiet_issues(team_id: int, dry_run: bool) -> int:
    count = auto_resolve.auto_resolve_issues(team_id, dry_run=dry_run)
    logger.info("error_tracking.auto_resolve.evaluated", team_id=team_id, issue_count=count, dry_run=dry_run)
    activity.metric_meter().create_counter("error_tracking_auto_resolve_issues").add(count, {"dry_run": dry_run})
    return count
