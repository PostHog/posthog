from datetime import timedelta
from typing import Any

from posthog.schema import ProductKey

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.materialized_columns import get_materialized_column_for_property
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.models.team.team import Team

from products.error_tracking.backend.models import ErrorTrackingIssue

from .base import Recommendation

ISSUE_LIMIT = 5

BATCH_QUERY = """
    SELECT
        events.team_id AS team_id,
        issue_state.issue_id AS issue_id,
        any(issue_state.first_seen) AS first_seen,
        count() AS occurrences
    FROM events
    INNER JOIN (
        SELECT
            team_id,
            fp_hash,
            tupleElement(state, 1) AS issue_id,
            tupleElement(state, 2) AS first_seen,
            tupleElement(state, 3) AS issue_status
        FROM (
            SELECT
                team_id,
                cityHash64(fingerprint) AS fp_hash,
                argMax((issue_id, first_seen, issue_status), version) AS state
            FROM error_tracking_fingerprint_issue_state
            WHERE team_id IN %(team_ids)s
            GROUP BY team_id, fp_hash
            HAVING argMax(is_deleted, version) = 0
            SETTINGS optimize_aggregation_in_order=1
        )
    ) AS issue_state
        ON events.team_id = issue_state.team_id
        AND cityHash64({fingerprint_expr}) = issue_state.fp_hash
    WHERE events.team_id IN %(team_ids)s
        AND events.event = '$exception'
        AND events.timestamp >= now() - INTERVAL 7 DAY
        AND issue_state.issue_status = 'active'
        AND issue_state.first_seen < now() - INTERVAL 7 DAY
    GROUP BY team_id, issue_id
    ORDER BY team_id ASC, first_seen ASC
    LIMIT %(issue_limit)s BY team_id
"""


def _fingerprint_expr() -> str:
    column = get_materialized_column_for_property("events", "properties", "$exception_fingerprint")
    if column is None:
        return "JSONExtractString(events.properties, '$exception_fingerprint')"
    if column.is_nullable:
        return f"ifNull(events.`{column.name}`, '')"
    return f"events.`{column.name}`"


class LongRunningIssuesRecommendation(Recommendation):
    type = "long_running_issues"
    refresh_interval = timedelta(hours=6)

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        tag_queries(
            product=ProductKey.ERROR_TRACKING,
            feature=Feature.ENRICHMENT,
            name="recommendations:long_running_issues",
        )

        rows = sync_execute(
            BATCH_QUERY.format(fingerprint_expr=_fingerprint_expr()),
            {"team_ids": team_ids, "issue_limit": ISSUE_LIMIT},
            workload=Workload.OFFLINE,
        )

        issues_by_id = {
            issue.id: issue
            # nosemgrep: idor-lookup-without-team (team_id__in scopes the lookup; background sweep, not user input)
            for issue in ErrorTrackingIssue.objects.filter(
                team_id__in=team_ids, id__in=[issue_id for _, issue_id, _, _ in rows]
            ).only("id", "name", "description", "status")
        }

        metas: dict[int, dict[str, Any]] = {team_id: {"issues": []} for team_id in team_ids}
        for team_id, issue_id, first_seen, occurrences in rows:
            issue = issues_by_id.get(issue_id)
            # Stale state rows can reference issues deleted from Postgres — skip them.
            if issue is None or first_seen is None:
                continue
            metas[team_id]["issues"].append(
                {
                    "id": str(issue_id),
                    "name": issue.name or "Untitled issue",
                    "description": issue.description,
                    "created_at": first_seen.isoformat(),
                    "occurrences": occurrences,
                    "status": issue.status,
                }
            )
        return metas

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
