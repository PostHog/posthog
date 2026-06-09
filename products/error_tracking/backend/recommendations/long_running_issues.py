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

# Cross-team variant of the per-team HogQL query, on the offline cluster. The issue
# state join carries only issue_id/first_seen/issue_status — pulling issue_name and
# issue_description strings through the argMax states and join hash table blows query
# memory once a few high-volume teams share a batch; names and descriptions come from
# Postgres afterwards. Unlike the HogQL version this does not apply per-team test
# account filters (impossible to express cross-team, acceptable for a recommendation
# card).
BATCH_QUERY = """
    SELECT
        events.team_id AS team_id,
        events__state.issue_id AS issue_id,
        any(events__state.first_seen) AS first_seen,
        count() AS occurrences
    FROM events
    INNER JOIN (
        SELECT
            team_id,
            cityHash64(fingerprint) AS fp_hash,
            tupleElement(argMax(tuple(issue_id), version), 1) AS issue_id,
            tupleElement(argMax(tuple(first_seen), version), 1) AS first_seen,
            tupleElement(argMax(tuple(issue_status), version), 1) AS issue_status
        FROM error_tracking_fingerprint_issue_state
        WHERE team_id IN %(team_ids)s
        GROUP BY team_id, fp_hash
        HAVING argMax(is_deleted, version) = 0
        SETTINGS optimize_aggregation_in_order=1
    ) AS events__state
        ON events.team_id = events__state.team_id
        AND cityHash64({fingerprint_expr}) = events__state.fp_hash
    WHERE events.team_id IN %(team_ids)s
        AND events.event = '$exception'
        AND events.timestamp >= now() - INTERVAL 7 DAY
        AND events__state.issue_status = 'active'
        AND events__state.first_seen < now() - INTERVAL 7 DAY
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

    def compute(self, team: Team) -> dict[str, Any]:
        return self.compute_batch([team.id])[team.id]

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
