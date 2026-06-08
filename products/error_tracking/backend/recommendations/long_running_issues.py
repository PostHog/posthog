from datetime import datetime, timedelta
from typing import Any

from asgiref.sync import async_to_sync

from posthog.schema import HogQLFilters, ProductKey

from posthog.hogql import ast

from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.models.team.team import Team

from products.error_tracking.backend.models import ErrorTrackingIssue
from products.signals.backend.facade.api import emit_signal

from .base import Recommendation

ISSUE_LIMIT = 10
SIGNAL_WEIGHT = 0.5


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

    def emit_signals(self, team: Team, old_meta: dict[str, Any], new_meta: dict[str, Any]) -> None:
        old_ids = {issue["id"] for issue in (old_meta.get("issues") or [])}
        for issue in new_meta.get("issues") or []:
            if issue["id"] in old_ids:
                continue
            description = (
                f"Long-running error tracking issue, still active 7+ days after it first appeared:\n"
                f"{issue['name']}: {issue.get('description') or ''}\n"
                f"Occurrences (last 7 days): {issue['occurrences']}\n"
                f"First seen: {issue['created_at']}"
            )
            async_to_sync(emit_signal)(
                team=team,
                source_product="error_tracking",
                source_type="long_running_issue",
                source_id=issue["id"],
                description=description,
                weight=SIGNAL_WEIGHT,
                extra={
                    "occurrences": issue["occurrences"],
                    "first_seen": issue["created_at"],
                    "status": str(issue["status"]),
                },
            )
