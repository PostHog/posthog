from datetime import timedelta
from typing import Any

from posthog.schema import HogQLFilters, ProductKey

from posthog.clickhouse.query_tagging import tag_queries
from posthog.models.team.team import Team

from products.error_tracking.backend.models import ErrorTrackingIssue

from .base import Recommendation

ISSUE_LIMIT = 10


class LongRunningIssuesRecommendation(Recommendation):
    type = "long_running_issues"
    refresh_interval = timedelta(hours=1)

    def compute(self, team: Team) -> dict[str, Any]:
        from posthog.hogql.query import execute_hogql_query

        tag_queries(
            product=ProductKey.ERROR_TRACKING,
            team_id=team.pk,
            name="recommendations:long_running_issues",
        )

        # Issues with at least one exception event in the last 7 days.
        response = execute_hogql_query(
            query="""
                SELECT DISTINCT issue_id
                FROM events
                WHERE event = '$exception'
                AND timestamp >= now() - INTERVAL 7 DAY
                AND issue_id IS NOT NULL
                AND {filters}
            """,
            team=team,
            filters=HogQLFilters(filterTestAccounts=True),
        )

        recent_issue_ids = [row[0] for row in (response.results or []) if row[0]]
        if not recent_issue_ids:
            return {"issues": []}

        issues = list(
            ErrorTrackingIssue.objects.filter(
                team=team,
                id__in=recent_issue_ids,
                status=ErrorTrackingIssue.Status.ACTIVE,
            ).order_by("created_at")[:ISSUE_LIMIT]
        )

        return {
            "issues": [
                {
                    "id": str(issue.id),
                    "name": issue.name or "Untitled issue",
                    "description": issue.description,
                    "created_at": issue.created_at.isoformat(),
                }
                for issue in issues
            ]
        }
