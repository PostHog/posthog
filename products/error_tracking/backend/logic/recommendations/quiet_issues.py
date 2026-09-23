from datetime import timedelta
from typing import Any

from posthog.schema import ProductKey

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.models.team.team import Team

from products.error_tracking.backend.models import ErrorTrackingIssue

from .base import Recommendation
from .fingerprints import FINGERPRINT_STATE_QUERY, fingerprint_expr

ISSUE_LIMIT = 5
QUIET_DAYS = 30

# The inverse of long_running_issues: active issues that stopped firing. An issue is quiet
# when it was first seen before the window and no exception landed on it inside the window,
# which the anti join expresses. Counting the whole quiet set, not only the sample, lets the
# card show how much of the active list has gone dead.
BATCH_QUERY = """
    WITH
    fingerprint_state AS ({fingerprint_state}),
    seen_in_window AS (
        SELECT DISTINCT
            events.team_id AS team_id,
            fingerprint_state.issue_id AS issue_id
        FROM events
        INNER JOIN fingerprint_state
            ON events.team_id = fingerprint_state.team_id
            AND cityHash64({fingerprint_expr}) = fingerprint_state.fp_hash
        WHERE events.team_id IN %(team_ids)s
            AND events.event = '$exception'
            AND events.timestamp >= now() - INTERVAL {quiet_days} DAY
    ),
    active_issues AS (
        SELECT
            team_id,
            issue_id,
            min(first_seen) AS first_seen
        FROM fingerprint_state
        WHERE issue_status = 'active'
        GROUP BY team_id, issue_id
        HAVING first_seen < now() - INTERVAL {quiet_days} DAY
    )
    SELECT
        active_issues.team_id AS team_id,
        active_issues.issue_id AS issue_id,
        active_issues.first_seen AS first_seen,
        count() OVER (PARTITION BY active_issues.team_id) AS quiet_total
    FROM active_issues
    LEFT ANTI JOIN seen_in_window
        ON active_issues.team_id = seen_in_window.team_id
        AND active_issues.issue_id = seen_in_window.issue_id
    ORDER BY team_id ASC, first_seen ASC
    LIMIT %(issue_limit)s BY team_id
"""


class QuietIssuesRecommendation(Recommendation):
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

        metas: dict[int, dict[str, Any]] = {
            team_id: {"quiet_days": QUIET_DAYS, "total": 0, "issues": []} for team_id in team_ids
        }
        for team_id, issue_id, first_seen, quiet_total in rows:
            issue = issues_by_id.get(issue_id)
            # Stale state rows can reference issues deleted from Postgres — skip them.
            if issue is None or first_seen is None:
                continue
            metas[team_id]["total"] = quiet_total
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
