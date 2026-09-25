from datetime import timedelta
from typing import Any

from posthog.schema import ProductKey

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.clickhouse.workload import Workload

from .fingerprints import FINGERPRINT_STATE_QUERY, fingerprint_expr
from .issue_list import IssueListRecommendation

ISSUE_LIMIT = 5

BATCH_QUERY = """
    SELECT
        events.team_id AS team_id,
        issue_state.issue_id AS issue_id,
        any(issue_state.first_seen) AS first_seen,
        count() AS occurrences
    FROM events
    INNER JOIN ({fingerprint_state}) AS issue_state
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


class LongRunningIssuesRecommendation(IssueListRecommendation):
    type = "long_running_issues"
    refresh_interval = timedelta(hours=6)

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        tag_queries(
            product=ProductKey.ERROR_TRACKING,
            feature=Feature.ENRICHMENT,
            name="recommendations:long_running_issues",
        )

        rows = sync_execute(
            BATCH_QUERY.format(fingerprint_expr=fingerprint_expr(), fingerprint_state=FINGERPRINT_STATE_QUERY),
            {"team_ids": team_ids, "issue_limit": ISSUE_LIMIT},
            workload=Workload.OFFLINE,
        )

        issues_by_id = self.issues_by_id(team_ids, [issue_id for _, issue_id, _, _ in rows])

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
