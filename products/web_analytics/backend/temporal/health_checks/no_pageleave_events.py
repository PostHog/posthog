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
SELECT
    team_id,
    countIf(event = '$pageview') AS pageviews,
    uniqIf(`$session_id`, event = '$pageview' AND `$session_id` != '') AS sessions
FROM events
WHERE team_id IN %(team_ids)s
  AND event IN ('$pageview', '$pageleave')
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
GROUP BY team_id
HAVING countIf(event = '$pageview') > 0
   AND countIf(event = '$pageleave') = 0
"""


def _estimate_pageleave_ratio(pageviews: int, sessions: int) -> float | None:
    """Estimate the extra events that enabling $pageleave adds, as a fraction of $pageview.

    Turning on $pageleave adds about one event per session, because the SDK fires
    $pageleave when the user leaves the page. As a share of $pageview that is
    sessions / pageviews: a single-page app packs many $pageview into one session, so
    it pays almost nothing; a project with one $pageview per session pays close to 1x.
    Returns None when there are no sessions to estimate from.
    """
    if sessions <= 0 or pageviews <= 0:
        return None
    return min(1.0, sessions / pageviews)


def _volume_estimate_sentence(payload: dict) -> str | None:
    """One-line volume estimate for the recommendation copy, or None when not known."""
    ratio = payload.get("estimated_pageleave_ratio")
    if ratio is None:
        return None
    percent = round(ratio * 100)
    if percent < 1:
        return "Enabling `$pageleave` adds less than 1% more events for this project."
    return f"Enabling `$pageleave` adds about {percent}% more events for this project."


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
            when the user navigates away. The extra volume is modest: $pageleave adds about one event per
            session, so a single-page app pays almost nothing and a project with one $pageview per session
            pays at most 1x more events. The health page shows the estimate for this project.
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
        summary = issue.payload.get("reason", "$pageview events present but no $pageleave events")
        estimate = _volume_estimate_sentence(issue.payload)
        if estimate:
            summary = f"{summary}. {estimate}"
        return AlertContent(
            title="No $pageleave events",
            summary=summary,
            link="/web/health",
        )

    @classmethod
    def render_signal(cls, issue: HealthIssue) -> SignalContent | None:
        title = "No $pageleave events"
        summary = issue.payload.get("reason", "$pageview events present but no $pageleave events.")
        description = (
            f"This project is sending `$pageview` events but no `$pageleave` events over the last "
            f"{NO_PAGELEAVE_LOOKBACK_DAYS} days. Missing `$pageleave` breaks bounce rate, session "
            "duration, and scroll-depth metrics in web analytics — it usually means "
            "`capture_pageleave` is disabled in the SDK config. Recommend enabling pageleave capture."
        )
        estimate = _volume_estimate_sentence(issue.payload)
        if estimate:
            description = f"{description} {estimate}"
        return SignalContent(
            description=description,
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
        for team_id, pageviews, sessions in rows:
            payload: dict = {
                "reason": f"Team has $pageview events but no $pageleave events in last {NO_PAGELEAVE_LOOKBACK_DAYS} days"
            }
            ratio = _estimate_pageleave_ratio(pageviews, sessions)
            if ratio is not None:
                payload["estimated_pageleave_ratio"] = ratio
            issues[team_id] = [
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING,
                    payload=payload,
                    hash_keys=[],
                )
            ]

        return issues
