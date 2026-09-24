from django.db import transaction

from products.error_tracking.backend.models import ErrorTrackingIssue, sync_issues_to_clickhouse

MAX_ISSUES_PER_SYNC = 1000


def retry_auto_resolve_sync(team_id: int) -> None:
    with transaction.atomic():
        issue_ids = list(
            ErrorTrackingIssue.objects.select_for_update(of=("self",))
            .filter(team_id=team_id, auto_resolve_sync_requested_at__isnull=False)
            .order_by("id")
            .values_list("id", flat=True)[:MAX_ISSUES_PER_SYNC]
        )
        if not issue_ids:
            return

        # Hold the locks until delivery so a retry publishes the latest issue state.
        sync_issues_to_clickhouse(issue_ids=issue_ids, team_id=team_id, wait_for_delivery=True)
        ErrorTrackingIssue.objects.filter(team_id=team_id, id__in=issue_ids).update(auto_resolve_sync_requested_at=None)
