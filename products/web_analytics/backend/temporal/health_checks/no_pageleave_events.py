from posthog.clickhouse.query_tagging import Product
from posthog.job_owners import JobOwners
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

# The ratio tracks how much navigation leaves the page, so it is not a fixed multiple of $pageview.
PAGELEAVE_VOLUME_NOTE = (
    "Volume: on a site with full page loads, $pageleave adds about 1 extra event per pageview. "
    "On a single-page app it adds well under 0.1, because most navigation never leaves the page."
)


class NoPageleaveEventsCheck(HealthCheck):
    name = "no_pageleave_events"
    kind = "no_pageleave_events"
    owner = JobOwners.TEAM_WEB_ANALYTICS
    product = Product.WEB_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "30 3 * * *"
    active_since_days = 30
    remediation = Remediation(
        human=f"""
            Open the Web analytics health page. The fix is almost always on the SDK side — make sure you're
            on a recent posthog-js with pageview autocapture enabled, which emits $pageleave automatically
            when the user navigates away. {PAGELEAVE_VOLUME_NOTE} In return you get scroll depth, which
            rides on $pageleave, and accurate bounce rate.
        """,
        agent=f"""
            Use `execute-sql` to confirm the gap (`SELECT event, count() FROM events WHERE event IN
            ('$pageview', '$pageleave') AND timestamp > now() - INTERVAL 7 DAY GROUP BY event`). Then fix it
            in the user's codebase: locate the `posthog.init` call and ensure pageview autocapture is
            enabled; if pageviews are captured manually (`capture_pageview: false`), add a matching
            `posthog.capture` of `$pageleave` on route changes / unload. Use `docs-search` for the
            pageview/pageleave capture docs. Tell the user what the change costs before they make it.
            {PAGELEAVE_VOLUME_NOTE} Say what they get for it — scroll depth, which rides on $pageleave, and
            accurate bounce rate. Once $pageleave events arrive, the issue resolves on the next check run.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        return AlertContent(
            title="No $pageleave events",
            summary=(
                f"{issue.payload.get('reason', '$pageview events present but no $pageleave events')}. "
                f"{PAGELEAVE_VOLUME_NOTE}"
            ),
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
                "`capture_pageleave` is disabled in the SDK config. Recommend enabling pageleave capture. "
                + PAGELEAVE_VOLUME_NOTE
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
