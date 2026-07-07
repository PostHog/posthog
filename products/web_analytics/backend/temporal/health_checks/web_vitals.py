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

WEB_VITALS_LOOKBACK_DAYS = 30
WEB_VITALS_SQL = """
SELECT team_id
FROM events
WHERE team_id IN %(team_ids)s
  AND event IN ('$pageview', '$web_vitals')
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
GROUP BY team_id
HAVING countIf(event = '$pageview') > 0
   AND countIf(event = '$web_vitals') = 0
"""


class WebVitalsCheck(HealthCheck):
    name = "web_vitals"
    kind = "web_vitals"
    owner = JobOwners.TEAM_WEB_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "30 5 * * *"
    active_since_days = 30
    remediation = Remediation(
        human="""
            Open the Web analytics health page. Web vitals are collected by posthog-js when performance
            capture is enabled, so make sure you're on a recent posthog-js and that `capture_performance`
            (web vitals) hasn't been turned off.
        """,
        agent="""
            Confirm none are arriving with `execute-sql` (`SELECT count() FROM events WHERE event =
            '$web_vitals' AND timestamp > now() - INTERVAL 7 DAY`). Then fix it in the user's codebase:
            bump posthog-js to a recent version and enable web vitals in the `posthog.init` config (the
            `capture_performance: { web_vitals: true }` option). Use `docs-search` for the web vitals /
            `capture_performance` docs. Once $web_vitals events start arriving, the issue resolves on the
            next check run.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        return AlertContent(
            title="No web vitals events",
            summary=issue.payload.get("reason", "$web_vitals events are not being received"),
            link="/web/health",
        )

    @classmethod
    def render_signal(cls, issue: HealthIssue) -> SignalContent | None:
        title = "No web vitals events"
        summary = issue.payload.get("reason", "$web_vitals events are not being received.")
        return SignalContent(
            description=(
                f"This project is sending `$pageview` events but no `$web_vitals` events over the last "
                f"{WEB_VITALS_LOOKBACK_DAYS} days, so Core Web Vitals (LCP, CLS, INP, FCP) won't appear in web "
                "analytics. This usually means web-vitals autocapture is disabled in the SDK config. Recommend "
                "enabling it to track page performance."
            ),
            weight=_SEVERITY_WEIGHT[issue.severity],
            extra=build_signal_extra(issue, title=title, summary=summary, link="/web/health"),
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        rows = execute_clickhouse_health_team_query(
            WEB_VITALS_SQL,
            team_ids=team_ids,
            lookback_days=WEB_VITALS_LOOKBACK_DAYS,
        )

        issues: dict[int, list[HealthCheckResult]] = {}
        for (team_id,) in rows:
            issues[team_id] = [
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING,
                    payload={
                        "reason": f"Team has $pageview events but no $web_vitals events in last {WEB_VITALS_LOOKBACK_DAYS} days"
                    },
                    hash_keys=[],
                )
            ]

        return issues
