import structlog

from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingSettings

logger = structlog.get_logger(__name__)

MAX_ISSUES_PER_TEAM_RUN = 1000


def get_auto_resolve_team_ids() -> list[int]:
    enabled_team_ids = (
        ErrorTrackingSettings.objects.filter(auto_resolve_after_days__isnull=False)
        .order_by()
        .values_list("team_id", flat=True)
    )
    # Pending writes must still reach ClickHouse after auto-resolve is disabled.
    pending_team_ids = (
        ErrorTrackingIssue.objects.filter(auto_resolve_sync_requested_at__isnull=False)
        .order_by()
        .values_list("team_id", flat=True)
        .distinct()
    )
    return sorted(set(enabled_team_ids).union(pending_team_ids))


def auto_resolve_team(team_id: int) -> int:
    # Lifecycle events import the Temporal package, which imports this module through activities.
    from products.error_tracking.backend.logic.auto_resolve_sync import retry_auto_resolve_sync  # noqa: PLC0415
    from products.error_tracking.backend.logic.issue_mutations import auto_resolve_issues  # noqa: PLC0415

    retry_auto_resolve_sync(team_id)
    resolved = auto_resolve_issues(team_id, limit=MAX_ISSUES_PER_TEAM_RUN)
    logger.info("error_tracking.auto_resolve.team_complete", team_id=team_id, resolved=len(resolved))
    return len(resolved)
