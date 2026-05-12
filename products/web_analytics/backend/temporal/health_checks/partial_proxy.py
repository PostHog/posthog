from collections import defaultdict

from posthog.dags.common.owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import CLICKHOUSE_BATCH_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import HealthCheck
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.query import execute_clickhouse_health_team_query

PARTIAL_PROXY_LOOKBACK_DAYS = 7
MIN_EVENTS_PER_HOST = 50
MAX_HOSTS_IN_PAYLOAD = 10

PARTIAL_PROXY_SQL = """
SELECT
    team_id,
    JSONExtractString(properties, '$host') AS host,
    countIf(JSONHas(properties, '$lib_custom_api_host')) > 0 AS has_proxy,
    count() AS event_count
FROM events
WHERE team_id IN %(team_ids)s
  AND event IN ('$pageview', '$screen')
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
  AND JSONExtractString(properties, '$host') != ''
GROUP BY team_id, host
HAVING event_count >= %(min_events_per_host)s
"""


class PartialProxyCheck(HealthCheck):
    name = "partial_proxy"
    kind = "partial_proxy"
    owner = JobOwners.TEAM_WEB_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "45 6 * * *"
    active_since_days = 30

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        rows = execute_clickhouse_health_team_query(
            PARTIAL_PROXY_SQL,
            team_ids=team_ids,
            lookback_days=PARTIAL_PROXY_LOOKBACK_DAYS,
            params={"min_events_per_host": MIN_EVENTS_PER_HOST},
        )

        proxied_by_team: dict[int, list[str]] = defaultdict(list)
        unproxied_by_team: dict[int, list[str]] = defaultdict(list)
        for team_id, host, has_proxy, _event_count in rows:
            if has_proxy:
                proxied_by_team[team_id].append(host)
            else:
                unproxied_by_team[team_id].append(host)

        issues: dict[int, list[HealthCheckResult]] = {}
        for team_id, proxied in proxied_by_team.items():
            unproxied = unproxied_by_team.get(team_id, [])
            if not unproxied:
                continue
            issues[team_id] = [
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING,
                    payload={
                        "reason": "Reverse proxy is only configured on some hostnames. "
                        "Traffic from unproxied hosts is more likely to be blocked or have inaccurate geolocation.",
                        "proxied_hosts": sorted(proxied)[:MAX_HOSTS_IN_PAYLOAD],
                        "unproxied_hosts": sorted(unproxied)[:MAX_HOSTS_IN_PAYLOAD],
                    },
                    hash_keys=[],
                )
            ]

        return issues
