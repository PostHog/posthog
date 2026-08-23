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

# Short-window traffic-stop detector. It complements `no_live_events`, which only fires
# after 30 days with zero events. This one compares a project's last couple of days against
# its own recent baseline, so a previously active project that drops to zero is caught within
# a few days instead of a month. Detection needs a full 48-hour silent window and the check
# runs once a day, so the lag is about two to three days depending on when the stop lands
# relative to the daily run. To avoid flagging normal weekly gaps, the recent window is also
# compared against the same days one week earlier (see TRAFFIC_STOP_SEASONALITY_DAYS).
TRAFFIC_STOP_RECENT_DAYS = 2
TRAFFIC_STOP_BASELINE_DAYS = 14
# One week. The recent window is compared against the same days one week earlier, so a project
# with a weekly rhythm (for example a B2B site that is quiet at weekends) does not read as a
# traffic stop: the same low days appear in both windows. Without this, a rolling 48-hour window
# would flag an ordinary weekend gap as a critical outage.
TRAFFIC_STOP_SEASONALITY_DAYS = 7
# Only projects that were clearly active count. A project needs both a minimum event volume
# and events on enough distinct days in the baseline window, so a single burst of testing does
# not qualify as "previously active".
TRAFFIC_STOP_MIN_BASELINE_EVENTS = 100
TRAFFIC_STOP_MIN_ACTIVE_DAYS = 7
TRAFFIC_STOP_WINDOW_DAYS = TRAFFIC_STOP_BASELINE_DAYS + TRAFFIC_STOP_RECENT_DAYS
# Bounds of the same-length window one week before the recent window: [now-9d, now-7d].
TRAFFIC_STOP_PRIOR_WEEK_FROM = TRAFFIC_STOP_RECENT_DAYS + TRAFFIC_STOP_SEASONALITY_DAYS
TRAFFIC_STOP_PRIOR_WEEK_TO = TRAFFIC_STOP_SEASONALITY_DAYS
# The prior-week window must carry real traffic, not a single stray hit, or the seasonality guard
# is trivially defeated: one crawler visit, synthetic monitor, or internal pageview a week ago would
# let an ordinary quiet weekend read as a critical stop. The floor is roughly the baseline-proportional
# volume for this 2-day window (the baseline gate implies ~7 events/day). Tunable while the check
# canaries at 1%.
TRAFFIC_STOP_MIN_PRIOR_WEEK_EVENTS = 10

TRAFFIC_STOP_SQL = """
SELECT
    team_id,
    countIf(timestamp < now() - INTERVAL %(recent_days)s DAY) AS baseline_events,
    uniqExactIf(toDate(timestamp), timestamp < now() - INTERVAL %(recent_days)s DAY) AS baseline_active_days
FROM events
WHERE team_id IN %(team_ids)s
  AND event IN ('$pageview', '$screen')
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
GROUP BY team_id
HAVING baseline_events >= %(min_baseline_events)s
   AND baseline_active_days >= %(min_active_days)s
   AND countIf(timestamp >= now() - INTERVAL %(recent_days)s DAY) = 0
   AND countIf(timestamp >= now() - INTERVAL %(prior_week_from)s DAY
               AND timestamp < now() - INTERVAL %(prior_week_to)s DAY) >= %(min_prior_week_events)s
"""


class TrafficStopCheck(HealthCheck):
    name = "traffic_stop"
    kind = "traffic_stop"
    owner = JobOwners.TEAM_WEB_ANALYTICS
    product = Product.WEB_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "0 5 * * *"
    active_since_days = 30
    # Canary this new check at 1% of teams. It is the first health check to compare a project
    # against its own baseline, and its query has not yet run against real data, so widen the
    # rollout only after the thresholds prove out in production.
    rollout_percentage = 0.01
    remediation = Remediation(
        human="""
            Open the Web analytics health page. Your project was receiving events steadily and then stopped,
            so the tracking probably broke rather than was never set up. Check whether a recent deploy removed
            or changed the PostHog snippet or SDK init, rotated the project API key, or added a consent or
            ad-blocker gate that now blocks capture. Load a page on your site, then check Activity → Live
            events to confirm events arrive again.
        """,
        agent="""
            Use `execute-sql` to see when capture stopped (`SELECT toDate(timestamp) AS day, count() FROM
            events WHERE event IN ('$pageview', '$screen') AND timestamp > now() - INTERVAL 21 DAY GROUP BY
            day ORDER BY day`) — a clean cliff to zero on a specific day points to a change shipped that day.
            Then fix it in the user's codebase: find where PostHog is initialized, confirm `posthog.init`
            still runs with the correct project API key, and check recent commits around the cliff date for a
            removed snippet, a changed key, or a new gate on capture. Use `docs-search` for the install guide
            for the relevant framework. The issue resolves once events start arriving again.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        return AlertContent(
            title="Traffic stopped",
            summary=issue.payload.get("reason", "A previously active project stopped sending events"),
            link="/web/health",
        )

    @classmethod
    def render_signal(cls, issue: HealthIssue) -> SignalContent | None:
        title = "Traffic stopped"
        summary = issue.payload.get("reason", "A previously active project stopped sending events.")
        return SignalContent(
            description=(
                f"This project sent `$pageview` or `$screen` events steadily over the prior "
                f"{TRAFFIC_STOP_BASELINE_DAYS} days. It then sent none in the last {TRAFFIC_STOP_RECENT_DAYS} "
                "days. Tracking that was working has stopped. A recent deploy likely removed or broke the "
                "PostHog snippet or SDK, rotated the project API key, or gated capture. Web and product "
                "analytics stay blank until capture is restored. Check the change that shipped around the drop."
            ),
            weight=_SEVERITY_WEIGHT[issue.severity],
            extra=build_signal_extra(issue, title=title, summary=summary, link="/web/health"),
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        rows = execute_clickhouse_health_team_query(
            TRAFFIC_STOP_SQL,
            team_ids=team_ids,
            lookback_days=TRAFFIC_STOP_WINDOW_DAYS,
            params={
                "recent_days": TRAFFIC_STOP_RECENT_DAYS,
                "min_baseline_events": TRAFFIC_STOP_MIN_BASELINE_EVENTS,
                "min_active_days": TRAFFIC_STOP_MIN_ACTIVE_DAYS,
                "prior_week_from": TRAFFIC_STOP_PRIOR_WEEK_FROM,
                "prior_week_to": TRAFFIC_STOP_PRIOR_WEEK_TO,
                "min_prior_week_events": TRAFFIC_STOP_MIN_PRIOR_WEEK_EVENTS,
            },
        )

        issues: dict[int, list[HealthCheckResult]] = {}
        for team_id, baseline_events, baseline_active_days in rows:
            per_active_day = round(baseline_events / baseline_active_days)
            issues[team_id] = [
                HealthCheckResult(
                    severity=HealthIssue.Severity.CRITICAL,
                    payload={
                        "reason": (
                            f"Traffic stopped: {baseline_events} $pageview/$screen events over the prior "
                            f"{TRAFFIC_STOP_BASELINE_DAYS} days ({per_active_day}/day across "
                            f"{baseline_active_days} active days), but none in the last {TRAFFIC_STOP_RECENT_DAYS} days"
                        ),
                        "baseline_events": baseline_events,
                        "baseline_active_days": baseline_active_days,
                    },
                    # One active issue per team for this kind — the baseline numbers shift each run,
                    # so keep them out of the identity hash.
                    hash_keys=[],
                )
            ]

        return issues
