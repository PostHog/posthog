from posthog.clickhouse.query_tagging import Product
from posthog.constants import PAGEVIEW_EVENT, SCREEN_EVENT
from posthog.job_owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.framework import (
    _SEVERITY_WEIGHT,
    AlertContent,
    Remediation,
    SignalContent,
    build_signal_extra,
)
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.query import execute_clickhouse_health_team_query
from posthog.temporal.health_checks.rollups.checks import RollupHealthCheck
from posthog.temporal.health_checks.rollups.freshness import RollupWindow

from products.web_analytics.backend.models.health_rollups import EventsHealthDaily
from products.web_analytics.backend.temporal.health_checks.rollup_reads import EventsHealthTotals, events_health_totals
from products.web_analytics.backend.temporal.health_checks.web_projects import expected_web_events

NO_LIVE_EVENTS_LOOKBACK_DAYS = 30
WEB_EVENTS_ORDER = (PAGEVIEW_EVENT, SCREEN_EVENT)

LIVE_EVENTS_SINCE_SQL = """
SELECT DISTINCT team_id, event
FROM events
WHERE team_id IN %(team_ids)s
  AND event IN ('$pageview', '$screen')
  AND timestamp >= %(since)s
"""


class NoLiveEventsCheck(RollupHealthCheck):
    name = "no_live_events"
    kind = "no_live_events"
    owner = JobOwners.TEAM_ANALYTICS
    product = Product.WEB_ANALYTICS
    schedule = "30 4 * * *"
    active_since_days = 30
    rollup_model = EventsHealthDaily
    window_days = NO_LIVE_EVENTS_LOOKBACK_DAYS
    remediation = Remediation(
        human="""
            Open the Web analytics health page. The issue names the events that stopped: $pageview comes
            from your website and $screen from your mobile app. Confirm the PostHog snippet or SDK is
            installed and initialized there and that you're using the correct project API key (Project
            settings → find your Web snippet / API key). Load a page or open a screen, then check
            Activity → Live events to see if events arrive in real time.
        """,
        agent="""
            Use `execute-sql` to see whether any events at all are landing (`SELECT event, count() FROM
            events WHERE timestamp > now() - INTERVAL 7 DAY GROUP BY event ORDER BY 2 DESC`) — other events
            but none of the events the issue names points to autocapture being disabled; nothing at all
            points to the SDK not sending. The payload's `events` lists what stopped: `$pageview` means the
            web SDK, `$screen` means a mobile SDK. Then fix it in the user's codebase: find where PostHog is
            initialized for that platform and make sure it runs with the correct project API key. For the
            web, check that pageview autocapture is enabled (if `posthog.init` sets `capture_pageview:
            false`, either re-enable it or send `$pageview` manually on navigation). For mobile, check that
            screen view capture is enabled or that the app sends `$screen` on navigation. Use `docs-search`
            for the install guide for the relevant framework. The issue resolves once those events start
            arriving again.
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
                f"This project hasn't received any {_event_list(issue.payload.get('events', list(WEB_EVENTS_ORDER)))} "
                f"events in the last {NO_LIVE_EVENTS_LOOKBACK_DAYS} days. `$pageview` comes from the web SDK and "
                "`$screen` from the mobile SDKs. That usually means the PostHog snippet/SDK on that platform "
                "isn't installed, was removed, or is misconfigured, and analytics for it will stay empty until "
                "capture is restored. Recommend verifying the SDK is initialized and sending events."
            ),
            weight=_SEVERITY_WEIGHT[issue.severity],
            extra=build_signal_extra(issue, title=title, summary=summary, link="/web/health"),
        )

    def detect_from_rollup(self, team_ids: list[int], window: RollupWindow) -> dict[int, list[HealthCheckResult]]:
        expected = expected_web_events(team_ids)
        totals = events_health_totals(list(expected), window)
        silent = {
            team_id: {event for event in events if _rollup_count(totals[team_id], event) == 0}
            for team_id, events in expected.items()
        }
        silent = {team_id: events for team_id, events in silent.items() if events}
        if not silent:
            return {}
        rows = execute_clickhouse_health_team_query(
            LIVE_EVENTS_SINCE_SQL,
            team_ids=list(silent),
            params={"since": window.live_since.strftime("%Y-%m-%d %H:%M:%S")},
        )
        for team_id, event in rows:
            silent[team_id].discard(event)
        return {
            team_id: [_no_live_events_result(events, still_sending=events != expected[team_id])]
            for team_id, events in silent.items()
            if events
        }


def _rollup_count(totals: EventsHealthTotals, event: str) -> int:
    return totals.pageviews if event == PAGEVIEW_EVENT else totals.screens


def _event_list(events: list[str]) -> str:
    return " or ".join(f"`{event}`" for event in events)


def _no_live_events_result(events: set[str], *, still_sending: bool) -> HealthCheckResult:
    ordered = [event for event in WEB_EVENTS_ORDER if event in events]
    return HealthCheckResult(
        severity=HealthIssue.Severity.WARNING if still_sending else HealthIssue.Severity.CRITICAL,
        payload={
            "reason": f"No {' or '.join(ordered)} events in last {NO_LIVE_EVENTS_LOOKBACK_DAYS} days",
            "events": ordered,
        },
        # A warning hashes apart from the critical issue, so losing the last platform creates a new
        # issue and fires an alert instead of raising the severity of the open warning in place.
        hash_keys=["events"] if still_sending else [],
    )
