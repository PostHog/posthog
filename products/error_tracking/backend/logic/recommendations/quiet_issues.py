from datetime import timedelta
from typing import Any

from posthog.schema import ProductKey

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.clickhouse.workload import Workload

from .fingerprints import FINGERPRINT_STATE_QUERY, fingerprint_expr
from .issue_list import IssueListRecommendation

ISSUE_LIMIT = 5
# ClickHouse applies the per-team limit before Postgres hydration drops rows for deleted
# issues, and those rows sort first here, so ask for a margin and cut after hydration.
CANDIDATE_LIMIT = ISSUE_LIMIT * 4
QUIET_DAYS = 30

# The inverse of long_running_issues: active issues that stopped firing. An issue is quiet
# when it was first seen before the window and none of its fingerprints appear in the window.
# The aggregate over the left join answers that per issue, because a merged issue holds several
# fingerprints and one recent fingerprint keeps the whole issue alive. Counting the whole quiet
# set, not only the sample, lets the card show how much of the active list has gone dead.
BATCH_QUERY = """
    WITH seen_in_window AS (
        SELECT DISTINCT
            events.team_id AS team_id,
            cityHash64({fingerprint_expr}) AS fp_hash,
            1 AS matched
        FROM events
        WHERE events.team_id IN %(team_ids)s
            AND events.event = '$exception'
            AND events.timestamp >= now() - INTERVAL {quiet_days} DAY
    )
    SELECT
        team_id,
        issue_id,
        first_seen,
        count() OVER (PARTITION BY team_id) AS quiet_total
    FROM (
        SELECT
            issue_state.team_id AS team_id,
            issue_state.issue_id AS issue_id,
            min(issue_state.first_seen) AS first_seen,
            ifNull(max(recent.matched), 0) AS seen_recently
        FROM ({fingerprint_state}) AS issue_state
        LEFT JOIN seen_in_window AS recent
            ON issue_state.team_id = recent.team_id
            AND issue_state.fp_hash = recent.fp_hash
        WHERE issue_state.issue_status = 'active'
        GROUP BY team_id, issue_id
        HAVING seen_recently = 0
            AND first_seen < now() - INTERVAL {quiet_days} DAY
    )
    ORDER BY team_id ASC, first_seen ASC
    LIMIT %(issue_limit)s BY team_id
"""


class QuietIssuesRecommendation(IssueListRecommendation):
    type = "quiet_issues"
    # Quiet issues move slowly, so a daily sweep is enough. The window scan is wider than
    # the other recommendations', and this keeps that cost off the six-hourly cycle.
    refresh_interval = timedelta(hours=24)

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        tag_queries(
            product=ProductKey.ERROR_TRACKING,
            feature=Feature.ENRICHMENT,
            name="recommendations:quiet_issues",
        )

        rows = sync_execute(
            BATCH_QUERY.format(
                fingerprint_expr=fingerprint_expr(),
                fingerprint_state=FINGERPRINT_STATE_QUERY,
                quiet_days=QUIET_DAYS,
            ),
            {"team_ids": team_ids, "issue_limit": CANDIDATE_LIMIT},
            workload=Workload.OFFLINE,
        )

        issues_by_id = self.issues_by_id(team_ids, [issue_id for _, issue_id, _, _ in rows])

        metas: dict[int, dict[str, Any]] = {
            team_id: {"quiet_days": QUIET_DAYS, "total": 0, "issues": []} for team_id in team_ids
        }
        for team_id, issue_id, first_seen, quiet_total in rows:
            # The count covers the whole quiet set, so it holds even when every sampled row
            # below turns out to be stale.
            metas[team_id]["total"] = quiet_total
            issue = issues_by_id.get(issue_id)
            # Stale state rows can reference issues deleted from Postgres — skip them.
            if issue is None or first_seen is None:
                continue
            if len(metas[team_id]["issues"]) >= ISSUE_LIMIT:
                continue
            metas[team_id]["issues"].append(
                {
                    "id": str(issue_id),
                    "name": issue.name or "Untitled issue",
                    "description": issue.description,
                    "first_seen": first_seen.isoformat(),
                    "status": issue.status,
                }
            )
        return metas

    def is_completed(self, meta: dict[str, Any]) -> bool:
        # The count covers the whole quiet set, while `issues` holds a hydrated sample that an
        # issue deleted from Postgres can shorten, so only the count can say the work is done.
        return not meta.get("total")
