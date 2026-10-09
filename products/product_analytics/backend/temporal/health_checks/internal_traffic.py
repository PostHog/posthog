from typing import Any

from posthog.clickhouse.query_tagging import Product
from posthog.job_owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.models.team import Team
from posthog.temporal.health_checks.detectors import CLICKHOUSE_BATCH_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import AlertContent, HealthCheck, Remediation
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.query import execute_clickhouse_health_team_query

INTERNAL_TRAFFIC_LOOKBACK_DAYS = 7
MIN_INTERNAL_PAGEVIEWS = 50
MIN_INTERNAL_SHARE = 0.01
INTERNAL_HOST_PATTERN = r"(?i)^(localhost|[a-z0-9.-]+\.localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:[0-9]+)?$"
HOST_EXCLUDING_OPERATORS = {"is_not", "not_icontains", "not_regex"}
SETTINGS_LINK = "/settings/environment-customization#internal-user-filtering"

INTERNAL_TRAFFIC_SQL = """
SELECT
    team_id,
    countIf(match(JSONExtractString(properties, '$host'), %(internal_host_pattern)s)) AS internal_pageviews,
    count() AS pageviews
FROM events
WHERE team_id IN %(team_ids)s
  AND event = '$pageview'
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
GROUP BY team_id
HAVING internal_pageviews >= %(min_internal_pageviews)s
"""


def _excludes_internal_hosts(test_account_filters: list[dict[str, Any]] | None) -> bool:
    # ponytail: any negative filter on the host or URL counts, even one aimed at another host.
    # Match the filter value against INTERNAL_HOST_PATTERN if dry-run results show teams slipping through.
    return any(
        isinstance(f, dict)
        and f.get("key") in ("$host", "$current_url")
        and f.get("operator") in HOST_EXCLUDING_OPERATORS
        for f in test_account_filters or []
    )


class InternalTrafficCheck(HealthCheck):
    name = "internal_traffic"
    kind = "internal_traffic"
    owner = JobOwners.TEAM_ANALYTICS_PLATFORM
    product = Product.PRODUCT_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "15 5 * * *"
    active_since_days = 30
    dry_run = True
    remediation = Remediation(
        human="""
            Pageviews from localhost are local development traffic, and they inflate your user and pageview
            counts. In Settings, open "Filter out internal and test users" and add a filter on the Host
            property that excludes localhost (for example, Host doesn't match regex `localhost|127\\.0\\.0\\.1`).
            Turn on "Enable this filter on all new insights". To stop the traffic at the source, initialize
            PostHog only in production builds.
        """,
        agent="""
            Confirm the hosts with `execute-sql` (`SELECT properties.$host, count() FROM events WHERE event =
            '$pageview' AND timestamp > now() - INTERVAL 7 DAY GROUP BY 1 ORDER BY 2 DESC`). To stop the traffic,
            find where `posthog.init` runs in the user's codebase and run it only in production, for example
            behind an environment check, or call `posthog.opt_out_capturing()` when the hostname is local. To
            filter data that is already captured, read the project's `test_account_filters` with `project-get`
            and append a `$host` filter with operator `not_regex` through `project-settings-update`. Keep every
            existing filter. The issue resolves when local pageviews drop below 1% of the total, or when the
            internal user filter excludes the host.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        share = issue.payload.get("internal_share", 0)
        return AlertContent(
            title="Local development traffic in your data",
            summary=f"{share:.0%} of pageviews in the last {INTERNAL_TRAFFIC_LOOKBACK_DAYS} days came from localhost",
            link=SETTINGS_LINK,
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        rows = execute_clickhouse_health_team_query(
            INTERNAL_TRAFFIC_SQL,
            team_ids=team_ids,
            lookback_days=INTERNAL_TRAFFIC_LOOKBACK_DAYS,
            params={"internal_host_pattern": INTERNAL_HOST_PATTERN, "min_internal_pageviews": MIN_INTERNAL_PAGEVIEWS},
        )
        if not rows:
            return {}

        filters_by_team = dict(
            Team.objects.filter(id__in=[team_id for team_id, *_ in rows]).values_list("id", "test_account_filters")
        )

        issues: dict[int, list[HealthCheckResult]] = {}
        for team_id, internal_pageviews, pageviews in rows:
            share = internal_pageviews / pageviews
            if share < MIN_INTERNAL_SHARE or _excludes_internal_hosts(filters_by_team.get(team_id)):
                continue
            issues[team_id] = [
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING,
                    payload={
                        "internal_pageviews": internal_pageviews,
                        "pageviews": pageviews,
                        "internal_share": round(share, 4),
                    },
                    hash_keys=[],
                )
            ]
        return issues
