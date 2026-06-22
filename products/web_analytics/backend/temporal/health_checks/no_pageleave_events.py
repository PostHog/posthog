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
    schedule = "30 3 * * *"
    active_since_days = 30
    remediation = Remediation(
        human="""
            Open the Web analytics health page. The fix is almost always on the SDK side — make sure you're
            on a recent posthog-js with pageview autocapture enabled, which emits $pageleave automatically
            when the user navigates away.
        """,
        agent="""
            Use `execute-sql` to confirm the gap (`SELECT event, count() FROM events WHERE event IN
            ('$pageview', '$pageleave') AND timestamp > now() - INTERVAL 7 DAY GROUP BY event`). Then fix it
            in the user's codebase: locate the `posthog.init` call and ensure pageview autocapture is
            enabled; if pageviews are captured manually (`capture_pageview: false`), add a matching
            `posthog.capture` of `$pageleave` on route changes / unload. Use `docs-search` for the
            pageview/pageleave capture docs. Once $pageleave events arrive, the issue resolves on the next
            check run.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        return AlertContent(
            title="No $pageleave events",
            summary=issue.payload.get("reason", "$pageview events present but no $pageleave events"),
            link="/web/health",
        )

    @classmethod
    def render_signal(cls, issue: HealthIssue) -> SignalContent | None:
        title = "No $pageleave events"
        summary = issue.payload.get("reason", "$pageview events present but no $pageleave events.")
        return SignalContent(
            description=(
                f"This project is sending `$pageview` events but no `$pageleave` events over the last "
                f"{NO_PAGELEAVE_LOOKBACK_DAYS} days. Missing `$pageleave` breaks bounce rate, session "
                "duration, and scroll-depth metrics in web analytics — it usually means "
                "`capture_pageleave` is disabled in the SDK config. Recommend enabling pageleave capture."
            ),
            weight=_SEVERITY_WEIGHT[issue.severity],
            extra=build_signal_extra(issue, title=title, summary=summary, link="/web/health"),
        )

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
