from posthog.clickhouse.query_tagging import Product
from posthog.job_owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import CLICKHOUSE_BATCH_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import AlertContent, HealthCheck, Remediation
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.query import execute_clickhouse_health_team_query

DUPLICATE_PAGEVIEWS_LOOKBACK_DAYS = 1
MIN_DUPLICATES = 100
MIN_DUPLICATE_SHARE = 0.05

# Two views of the same page or screen by the same person in the same second are one view sent twice. A pair that
# crosses a second boundary lands in two buckets and is not counted, so the share is a lower bound.
DUPLICATE_PAGEVIEWS_SQL = """
SELECT team_id, sum(views - 1) AS duplicates, sum(views) AS total
FROM (
    SELECT team_id, count() AS views
    FROM events
    WHERE team_id IN %(team_ids)s
      AND event IN ('$pageview', '$screen')
      AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
    GROUP BY
        team_id,
        distinct_id,
        event,
        JSONExtractString(properties, '$current_url'),
        JSONExtractString(properties, '$screen_name'),
        toStartOfSecond(timestamp)
)
GROUP BY team_id
HAVING duplicates >= %(min_duplicates)s
"""


class DuplicatePageviewsCheck(HealthCheck):
    name = "duplicate_pageviews"
    kind = "duplicate_pageviews"
    owner = JobOwners.TEAM_ANALYTICS_PLATFORM
    product = Product.PRODUCT_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "30 5 * * *"
    active_since_days = 30
    dry_run = True
    remediation = Remediation(
        human="""
            Your app sends some pageviews twice, so pageview counts, sessions, and funnels that start with a pageview
            are too high. The usual causes are PostHog starting twice (for example in a React effect that runs twice,
            or in both a layout and a page), or automatic pageview capture together with a manual `$pageview` capture
            on route change. Make sure `posthog.init` runs once, and capture pageviews in one way only.
        """,
        agent="""
            Find the pages with `execute-sql` (`SELECT properties.$current_url, count() - uniqExact(distinct_id,
            toStartOfSecond(timestamp)) AS duplicates FROM events WHERE event = '$pageview' AND timestamp > now() -
            INTERVAL 1 DAY GROUP BY 1 ORDER BY 2 DESC LIMIT 20`). In the user's codebase, find every `posthog.init`
            call and every `capture('$pageview')`. Check the `capture_pageview` option: with automatic capture on
            (the default, or `'history_change'`), a manual `$pageview` on navigation sends a second one. Also check
            that `posthog.init` is not inside a component or effect that runs more than once. Fix it so each page
            view sends one event. The issue resolves when duplicates drop below 5% of pageviews.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        share = issue.payload.get("duplicate_share", 0)
        return AlertContent(
            title="Pageviews sent twice",
            summary=f"{share:.0%} of pageviews in the last day were sent twice within one second",
            link="/web",
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        rows = execute_clickhouse_health_team_query(
            DUPLICATE_PAGEVIEWS_SQL,
            team_ids=team_ids,
            lookback_days=DUPLICATE_PAGEVIEWS_LOOKBACK_DAYS,
            params={"min_duplicates": MIN_DUPLICATES},
        )

        issues: dict[int, list[HealthCheckResult]] = {}
        for team_id, duplicates, total in rows:
            share = duplicates / total
            if share < MIN_DUPLICATE_SHARE:
                continue
            issues[team_id] = [
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING,
                    payload={"duplicate_pageviews": duplicates, "pageviews": total, "duplicate_share": round(share, 4)},
                    hash_keys=[],
                )
            ]
        return issues
