from datetime import datetime, timedelta
from typing import Any

from posthog.schema import HogQLFilters, ProductKey

from posthog.hogql import ast

from posthog.clickhouse.query_tagging import Feature, tag_queries
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
            feature=Feature.ENRICHMENT,
            team_id=team.pk,
            name="recommendations:long_running_issues",
        )

        response = execute_hogql_query(
            query="""
                SELECT
                    issue_id_v2,
                    any(issue_name) AS name,
                    any(issue_description) AS description,
                    any(issue_first_seen) AS first_seen,
                    count() AS occurrences
                FROM events
                WHERE event = '$exception'
                AND timestamp >= now() - INTERVAL 7 DAY
                AND issue_id_v2 IS NOT NULL
                AND issue_status = 'active'
                AND issue_first_seen < now() - INTERVAL 7 DAY
                AND {filters}
                GROUP BY issue_id_v2
                ORDER BY first_seen ASC
                LIMIT {limit}
            """,
            team=team,
            filters=HogQLFilters(filterTestAccounts=True),
            placeholders={"limit": ast.Constant(value=ISSUE_LIMIT)},
        )

        return {
            "issues": [
                {
                    "id": str(issue_id),
                    "name": name or "Untitled issue",
                    "description": description,
                    "created_at": first_seen.isoformat() if isinstance(first_seen, datetime) else first_seen,
                    "occurrences": occurrences,
                    "status": ErrorTrackingIssue.Status.ACTIVE,
                }
                for issue_id, name, description, first_seen, occurrences in (response.results or [])
                if issue_id and first_seen
            ]
        }

    def is_completed(self, meta: dict[str, Any]) -> bool:
        return not meta.get("issues")

    def enrich(self, team: Team, meta: dict[str, Any]) -> dict[str, Any]:
        issues = meta.get("issues") or []
        if not issues:
            return meta

        statuses = {
            str(row_id): row_status
            for row_id, row_status in ErrorTrackingIssue.objects.filter(
                team=team, id__in=[i["id"] for i in issues]
            ).values_list("id", "status")
        }
        return {
            **meta,
            "issues": [{**issue, "status": statuses.get(issue["id"], issue.get("status"))} for issue in issues],
        }
