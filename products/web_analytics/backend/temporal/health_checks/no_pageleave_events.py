from posthog.clickhouse.query_tagging import Product
from posthog.dags.common.owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import CLICKHOUSE_BATCH_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import HealthCheck
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.query import execute_clickhouse_health_team_query

NO_PAGELEAVE_LOOKBACK_DAYS = 30
NO_PAGELEAVE_SQL = """
SELECT team_id
FROM events
WHERE team_id IN %(team_ids)s
  AND event IN ('$pageview', '$pageleave')
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
GROUP BY team_id
HAVING countIf(event = '$pageview') > 0
   AND countIf(event = '$pageleave') = 0
"""


class NoPageleaveEventsCheck(HealthCheck):
    name = "no_pageleave_events"
    kind = "no_pageleave_events"
    owner = JobOwners.TEAM_WEB_ANALYTICS
    product = Product.WEB_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        rows = execute_clickhouse_health_team_query(
            NO_PAGELEAVE_SQL,
            team_ids=team_ids,
            lookback_days=NO_PAGELEAVE_LOOKBACK_DAYS,
        )

        issues: dict[int, list[HealthCheckResult]] = {}
        for (team_id,) in rows:
            issues[team_id] = [
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING,
                    payload={
                        "reason": f"Team has $pageview events but no $pageleave events in last {NO_PAGELEAVE_LOOKBACK_DAYS} days"
                    },
                    hash_keys=[],
                )
            ]

        return issues
