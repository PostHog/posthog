from posthog.dags.common.owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import CLICKHOUSE_BATCH_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import HealthCheck
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.query import execute_clickhouse_health_team_query

NO_LIVE_EVENTS_LOOKBACK_DAYS = 30
NO_LIVE_EVENTS_SQL = """
SELECT team_id
FROM events
WHERE team_id IN %(team_ids)s
  AND event IN ('$pageview', '$screen')
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
GROUP BY team_id
"""


class NoLiveEventsCheck(HealthCheck):
    name = "no_live_events"
    kind = "no_live_events"
    owner = JobOwners.TEAM_WEB_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        rows = execute_clickhouse_health_team_query(
            NO_LIVE_EVENTS_SQL,
            team_ids=team_ids,
            lookback_days=NO_LIVE_EVENTS_LOOKBACK_DAYS,
        )

        teams_with_recent_events = {team_id for team_id, *_ in rows}

        issues: dict[int, list[HealthCheckResult]] = {}
        for team_id in set(team_ids) - teams_with_recent_events:
            issues[team_id] = [
                HealthCheckResult(
                    severity=HealthIssue.Severity.CRITICAL,
                    payload={"reason": f"No $pageview or $screen events in last {NO_LIVE_EVENTS_LOOKBACK_DAYS} days"},
                    hash_keys=[],
                )
            ]

        return issues
