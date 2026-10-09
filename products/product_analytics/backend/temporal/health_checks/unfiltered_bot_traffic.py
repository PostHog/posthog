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

BOT_TRAFFIC_LOOKBACK_DAYS = 7
MIN_BOT_PAGEVIEWS = 50
MIN_BOT_SHARE = 0.01
WARNING_SHARE = 0.05
TRAFFIC_FILTER_KEYS = {"$virt_is_bot", "$virt_traffic_type", "$virt_traffic_category", "$virt_bot_name"}
SETTINGS_LINK = "/settings/environment-customization#internal-user-filtering"

# Crawlers only. The "Automation" type also covers events with no user agent, which server-side SDKs send, so a
# filter on it would hide real events.
CRAWLER_PATTERNS = [
    pattern for pattern, definition in BOT_DEFINITIONS.items() if definition.traffic_type in ("Bot", "AI Agent")
]

BOT_TRAFFIC_SQL = """
SELECT
    team_id,
    countIf(multiMatchAny(JSONExtractString(properties, '$raw_user_agent'), %(crawler_patterns)s)) AS bot_pageviews,
    count() AS pageviews
FROM events
WHERE team_id IN %(team_ids)s
  AND event = '$pageview'
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
GROUP BY team_id
HAVING bot_pageviews >= %(min_bot_pageviews)s
"""


def _filters_traffic_type(test_account_filters: list[Any] | None) -> bool:
    return any(isinstance(f, dict) and f.get("key") in TRAFFIC_FILTER_KEYS for f in test_account_filters or [])


class UnfilteredBotTrafficCheck(HealthCheck):
    name = "unfiltered_bot_traffic"
    kind = "unfiltered_bot_traffic"
    owner = JobOwners.TEAM_ANALYTICS_PLATFORM
    product = Product.PRODUCT_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "0 5 * * *"
    active_since_days = 30
    dry_run = True
    remediation = Remediation(
        human="""
            Bots and AI crawlers load your pages, and they count as users and pageviews in your insights. In
            Settings, open "Filter out internal and test users" and add a filter where Traffic type is not "Bot" and
            not "AI Agent". Do not use "Is bot" in this filter: it also matches events with no user agent, such as
            events your server sends, and it would hide them from every insight.
        """,
        agent="""
            Confirm the traffic with `execute-sql` (`SELECT $virt_traffic_type, $virt_bot_name, count() FROM events
            WHERE event = '$pageview' AND timestamp > now() - INTERVAL 7 DAY GROUP BY 1, 2 ORDER BY 3 DESC`). Read the
            project's `test_account_filters` with `project-get`, then append `{"key": "$virt_traffic_type", "value":
            ["Bot", "AI Agent"], "operator": "is_not", "type": "event"}` through `project-settings-update`, keeping
            every existing filter. Never add `$virt_is_bot` to `test_account_filters`, because it is true for every
            event without a user agent. The issue resolves when the internal user filter has a traffic filter.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        share = issue.payload.get("share", 0)
        return AlertContent(
            title="Bot traffic in your insights",
            summary=f"{share:.0%} of pageviews in the last {BOT_TRAFFIC_LOOKBACK_DAYS} days came from bots and crawlers",
            link=SETTINGS_LINK,
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        rows = execute_clickhouse_health_team_query(
            BOT_TRAFFIC_SQL,
            team_ids=team_ids,
            lookback_days=BOT_TRAFFIC_LOOKBACK_DAYS,
            params={"crawler_patterns": CRAWLER_PATTERNS, "min_bot_pageviews": MIN_BOT_PAGEVIEWS},
        )
        if not rows:
            return {}

        filters_by_team = dict(
            Team.objects.filter(id__in=[team_id for team_id, *_ in rows]).values_list("id", "test_account_filters")
        )

        issues: dict[int, list[HealthCheckResult]] = {}
        for team_id, bot_pageviews, pageviews in rows:
            share = bot_pageviews / pageviews
            if share < MIN_BOT_SHARE or _filters_traffic_type(filters_by_team.get(team_id)):
                continue
            issues[team_id] = [
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING if share >= WARNING_SHARE else HealthIssue.Severity.INFO,
                    payload={"bot_pageviews": bot_pageviews, "pageviews": pageviews, "share": round(share, 4)},
                    hash_keys=[],
                )
            ]
        return issues
