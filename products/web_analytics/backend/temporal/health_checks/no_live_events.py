from posthog.clickhouse.query_tagging import Product
from posthog.dags.common.owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import CLICKHOUSE_BATCH_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import (
    _SEVERITY_WEIGHT,
    AlertContent,
    HealthCheck,
    Remediation,
    SignalContent,
    build_signal_extra,
)
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
    product = Product.WEB_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "30 4 * * *"
    active_since_days = 30
    remediation = Remediation(
        human="""
            Open the Web analytics health page. Confirm the PostHog snippet or SDK is installed and
            initialized on your site or app and that you're using the correct project API key (Project
            settings → find your Web snippet / API key). Load a page on your site, then check Activity →
            Live events to see if events arrive in real time.
        """,
        agent="""
            Use `execute-sql` to see whether any events at all are landing (`SELECT event, count() FROM
            events WHERE timestamp > now() - INTERVAL 7 DAY GROUP BY event ORDER BY 2 DESC`) — other events
            but no $pageview/$screen points to autocapture being disabled; nothing at all points to the SDK
            not sending. Then fix it in the user's codebase: find where PostHog is initialized, make sure
            `posthog.init` runs with the correct project API key and that pageview autocapture is enabled
            (if it sets `capture_pageview: false`, either re-enable it or send `$pageview` manually on
            navigation). Use `docs-search` for the install guide for the relevant framework. The issue
            resolves once events start arriving again.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        return AlertContent(
            title="No live events",
            summary=issue.payload.get("reason", "No $pageview or $screen events received recently"),
            link="/web/health",
        )

    @classmethod
    def render_signal(cls, issue: HealthIssue) -> SignalContent | None:
        title = "No live events"
        summary = issue.payload.get("reason", "No $pageview or $screen events received recently.")
        return SignalContent(
            description=(
                f"This project hasn't received any `$pageview` or `$screen` events in the last "
                f"{NO_LIVE_EVENTS_LOOKBACK_DAYS} days. That usually means the PostHog snippet/SDK "
                "isn't installed, was removed, or is misconfigured — web and product analytics will "
                "stay empty until capture is restored. Recommend verifying the SDK is initialized "
                "and sending events."
            ),
            weight=_SEVERITY_WEIGHT[issue.severity],
            extra=build_signal_extra(issue, title=title, summary=summary, link="/web/health"),
        )

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
