from typing import Any

from posthog.clickhouse.query_tagging import Product
from posthog.job_owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.models.team import Team
from posthog.temporal.health_checks.detectors import CLICKHOUSE_BATCH_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import AlertContent, HealthCheck, Remediation
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.query import execute_clickhouse_health_team_query

LOCAL_TRAFFIC_LOOKBACK_DAYS = 7
# No share minimum: a local session also creates test persons, flag exposures and recordings, whatever its share.
# The floor only skips a single developer who tried something once.
MIN_LOCAL_PAGEVIEWS = 50
WARNING_SHARE = 0.01
LOCAL_HOST_PATTERN = r"(?i)^(localhost|[a-z0-9.-]+\.localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:[0-9]+)?$"
EXCLUDING_OPERATORS = {"is_not", "not_icontains", "not_regex"}
SETTINGS_LINK = "/settings/environment-customization#internal-user-filtering"

LOCAL_TRAFFIC_SQL = """
SELECT
    team_id,
    countIf(match(JSONExtractString(properties, '$host'), %(local_host_pattern)s)) AS local_pageviews,
    count() AS pageviews
FROM events
WHERE team_id IN %(team_ids)s
  AND event = '$pageview'
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
GROUP BY team_id
HAVING local_pageviews >= %(min_local_pageviews)s
"""


def _excludes_local_hosts(test_account_filters: list[Any] | None) -> bool:
    # ponytail: any negative filter on the host or URL counts, even one aimed at another host.
    # Match the filter value against LOCAL_HOST_PATTERN if dry-run results show teams slipping through.
    return any(
        isinstance(f, dict) and f.get("key") in ("$host", "$current_url") and f.get("operator") in EXCLUDING_OPERATORS
        for f in test_account_filters or []
    )


class LocalDevelopmentTrafficCheck(HealthCheck):
    name = "local_development_traffic"
    kind = "local_development_traffic"
    owner = JobOwners.TEAM_ANALYTICS_PLATFORM
    product = Product.PRODUCT_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "15 5 * * *"
    active_since_days = 30
    dry_run = True
    remediation = Remediation(
        human="""
            This project receives pageviews from local development. They add test users to your counts, funnels and
            experiments, and they use your recording and event quota. The best fix is to send local traffic to a
            separate PostHog project, or to initialize PostHog only in production builds. To hide what is already
            captured, open "Filter out internal and test users" in Settings, add a filter where Host doesn't match
            regex `localhost|127\\.0\\.0\\.1`, and turn on "Enable this filter on all new insights".
        """,
        agent="""
            Confirm the hosts with `execute-sql` (`SELECT properties.$host, count() FROM events WHERE event =
            '$pageview' AND timestamp > now() - INTERVAL 7 DAY GROUP BY 1 ORDER BY 2 DESC`). In the user's codebase,
            find where `posthog.init` runs and use a separate project token for development, or skip `posthog.init`
            outside production, for example behind an environment check. To hide data that is already captured,
            read the project's `test_account_filters` with `project-get` and append a `$host` filter with operator
            `not_regex` through `project-settings-update`, keeping every existing filter. The issue resolves when
            local pageviews stop, or when the internal user filter excludes the host.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        local_pageviews = issue.payload.get("local_pageviews", 0)
        return AlertContent(
            title="Local development traffic in your data",
            summary=f"{local_pageviews} pageviews in the last {LOCAL_TRAFFIC_LOOKBACK_DAYS} days came from localhost",
            link=SETTINGS_LINK,
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        rows = execute_clickhouse_health_team_query(
            LOCAL_TRAFFIC_SQL,
            team_ids=team_ids,
            lookback_days=LOCAL_TRAFFIC_LOOKBACK_DAYS,
            params={"local_host_pattern": LOCAL_HOST_PATTERN, "min_local_pageviews": MIN_LOCAL_PAGEVIEWS},
        )
        if not rows:
            return {}

        filters_by_team = dict(
            Team.objects.filter(id__in=[team_id for team_id, *_ in rows]).values_list("id", "test_account_filters")
        )

        issues: dict[int, list[HealthCheckResult]] = {}
        for team_id, local_pageviews, pageviews in rows:
            if _excludes_local_hosts(filters_by_team.get(team_id)):
                continue
            share = local_pageviews / pageviews
            issues[team_id] = [
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING if share >= WARNING_SHARE else HealthIssue.Severity.INFO,
                    payload={"local_pageviews": local_pageviews, "pageviews": pageviews, "share": round(share, 4)},
                    hash_keys=[],
                )
            ]
        return issues
