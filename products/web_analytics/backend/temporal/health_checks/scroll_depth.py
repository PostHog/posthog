from posthog.dags.common.owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import CLICKHOUSE_BATCH_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import HealthCheck
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.query import execute_clickhouse_health_team_query

SCROLL_DEPTH_LOOKBACK_DAYS = 30
SCROLL_DEPTH_SQL = """
SELECT team_id
FROM events
WHERE team_id IN %(team_ids)s
  AND event = '$pageleave'
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
GROUP BY team_id
HAVING countIf(position(properties, '"$prev_pageview_max_content_percentage"') > 0) = 0
"""


class ScrollDepthCheck(HealthCheck):
    name = "scroll_depth"
    kind = "scroll_depth"
    owner = JobOwners.TEAM_WEB_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        rows = execute_clickhouse_health_team_query(
            SCROLL_DEPTH_SQL,
            team_ids=team_ids,
            lookback_days=SCROLL_DEPTH_LOOKBACK_DAYS,
        )

        issues: dict[int, list[HealthCheckResult]] = {}
        for (team_id,) in rows:
            issues[team_id] = [
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING,
                    payload={
                        "reason": f"Team has $pageleave events but scroll depth tracking is not enabled in last {SCROLL_DEPTH_LOOKBACK_DAYS} days"
                    },
                    hash_keys=[],
                )
            ]

        return issues
