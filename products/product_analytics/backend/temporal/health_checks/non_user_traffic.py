from typing import Any

from posthog.clickhouse.query_tagging import Product
from posthog.job_owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.models.team import Team
from posthog.temporal.health_checks.detectors import CLICKHOUSE_BATCH_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import AlertContent, HealthCheck, Remediation
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.query import execute_clickhouse_health_team_query

from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS

NON_USER_TRAFFIC_LOOKBACK_DAYS = 7
MIN_MATCHING_PAGEVIEWS = 50
LOCAL_DEVELOPMENT = "local_development"
BOTS = "bots"
MIN_SHARE = {LOCAL_DEVELOPMENT: 0.01, BOTS: 0.05}
LOCAL_HOST_PATTERN = r"(?i)^(localhost|[a-z0-9.-]+\.localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:[0-9]+)?$"
EXCLUDING_OPERATORS = {"is_not", "not_icontains", "not_regex"}
BOT_FILTER_KEYS = {"$virt_is_bot", "$virt_traffic_type", "$virt_traffic_category"}
SETTINGS_LINK = "/settings/environment-customization#internal-user-filtering"

# Bots match on the user agent patterns that isLikelyBot uses. The IP ranges need the HogQL expansion, and an empty
# user agent is left out, because a server-side SDK sends pageviews without one.
NON_USER_TRAFFIC_SQL = """
SELECT
    team_id,
    countIf(match(JSONExtractString(properties, '$host'), %(local_host_pattern)s)) AS local_pageviews,
    countIf(multiMatchAny(JSONExtractString(properties, '$raw_user_agent'), %(bot_patterns)s)) AS bot_pageviews,
    count() AS pageviews
FROM events
WHERE team_id IN %(team_ids)s
  AND event = '$pageview'
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
GROUP BY team_id
HAVING local_pageviews >= %(min_matching_pageviews)s OR bot_pageviews >= %(min_matching_pageviews)s
"""


def _already_filtered(reason: str, test_account_filters: list[Any] | None) -> bool:
    filters = [f for f in test_account_filters or [] if isinstance(f, dict)]
    if reason == BOTS:
        return any(f.get("key") in BOT_FILTER_KEYS for f in filters)
    # ponytail: any negative filter on the host or URL counts, even one aimed at another host.
    # Match the filter value against LOCAL_HOST_PATTERN if dry-run results show teams slipping through.
    return any(f.get("key") in ("$host", "$current_url") and f.get("operator") in EXCLUDING_OPERATORS for f in filters)


class NonUserTrafficCheck(HealthCheck):
    name = "non_user_traffic"
    kind = "non_user_traffic"
    owner = JobOwners.TEAM_ANALYTICS_PLATFORM
    product = Product.PRODUCT_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "15 5 * * *"
    active_since_days = 30
    dry_run = True
    remediation = Remediation(
        human="""
            Pageviews from local development or from bots inflate your user and pageview counts. In Settings, open
            "Filter out internal and test users". For local development, add a filter on the Host property that
            excludes localhost (for example, Host doesn't match regex `localhost|127\\.0\\.0\\.1`). For bots, add a
            filter on "Is bot" equal to false. Turn on "Enable this filter on all new insights". To stop local
            traffic at the source, initialize PostHog only in production builds.
        """,
        agent="""
            Read `reason` in the payload. Confirm the traffic with `execute-sql`: for local development, `SELECT
            properties.$host, count() FROM events WHERE event = '$pageview' AND timestamp > now() - INTERVAL 7 DAY
            GROUP BY 1 ORDER BY 2 DESC`; for bots, `SELECT $virt_bot_name, count() FROM events WHERE event =
            '$pageview' AND timestamp > now() - INTERVAL 7 DAY AND $virt_is_bot GROUP BY 1 ORDER BY 2 DESC`. To
            filter data, read the project's `test_account_filters` with `project-get` and append one filter with
            `project-settings-update`, keeping every existing filter: `$host` with operator `not_regex` for local
            development, or `{"key": "$virt_is_bot", "value": ["false"], "operator": "exact", "type": "event"}` for
            bots. To stop local traffic, find where `posthog.init` runs in the user's codebase and run it only in
            production. The issue resolves when the traffic drops below the threshold or the filter excludes it.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        share = issue.payload.get("share", 0)
        source = "bots" if issue.payload.get("reason") == BOTS else "local development"
        return AlertContent(
            title=f"Pageviews from {source} in your data",
            summary=f"{share:.0%} of pageviews in the last {NON_USER_TRAFFIC_LOOKBACK_DAYS} days came from {source}",
            link=SETTINGS_LINK,
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        rows = execute_clickhouse_health_team_query(
            NON_USER_TRAFFIC_SQL,
            team_ids=team_ids,
            lookback_days=NON_USER_TRAFFIC_LOOKBACK_DAYS,
            params={
                "local_host_pattern": LOCAL_HOST_PATTERN,
                "bot_patterns": list(BOT_DEFINITIONS.keys()),
                "min_matching_pageviews": MIN_MATCHING_PAGEVIEWS,
            },
        )
        if not rows:
            return {}

        filters_by_team = dict(
            Team.objects.filter(id__in=[team_id for team_id, *_ in rows]).values_list("id", "test_account_filters")
        )

        issues: dict[int, list[HealthCheckResult]] = {}
        for team_id, local_pageviews, bot_pageviews, pageviews in rows:
            results = []
            for reason, matching in ((LOCAL_DEVELOPMENT, local_pageviews), (BOTS, bot_pageviews)):
                share = matching / pageviews
                if matching < MIN_MATCHING_PAGEVIEWS or share < MIN_SHARE[reason]:
                    continue
                if _already_filtered(reason, filters_by_team.get(team_id)):
                    continue
                results.append(
                    HealthCheckResult(
                        severity=HealthIssue.Severity.WARNING,
                        payload={
                            "reason": reason,
                            "matching_pageviews": matching,
                            "pageviews": pageviews,
                            "share": round(share, 4),
                        },
                        hash_keys=["reason"],
                    )
                )
            if results:
                issues[team_id] = results
        return issues
