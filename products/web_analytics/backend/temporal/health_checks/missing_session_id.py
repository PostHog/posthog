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

MISSING_SESSION_ID_LOOKBACK_DAYS = 30

# Web analytics drops any $pageview whose $session_id is empty or not a UUID, so
# those events never reach a session and undercount every aggregate. A healthy
# project sits near zero, so warn only above a share threshold and require a
# volume floor to stay quiet on low-traffic noise.
MISSING_SESSION_ID_THRESHOLD = 0.05
MISSING_SESSION_ID_MIN_PAGEVIEWS = 10_000

# `$session_id_uuid` is NULL exactly when `$session_id` is missing or malformed —
# the same guard web analytics uses to exclude the event (events_session_id_present).
MISSING_SESSION_ID_SQL = """
SELECT
    team_id,
    count() AS total_pageviews,
    countIf(`$session_id_uuid` IS NULL) AS missing_session_id
FROM events
WHERE team_id IN %(team_ids)s
  AND event = '$pageview'
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
GROUP BY team_id
HAVING total_pageviews >= %(min_pageviews)s
   AND missing_session_id >= total_pageviews * %(threshold)s
"""


class MissingSessionIdCheck(HealthCheck):
    name = "missing_session_id"
    kind = "missing_session_id"
    owner = JobOwners.TEAM_WEB_ANALYTICS
    product = Product.WEB_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "0 6 * * *"
    active_since_days = 30
    remediation = Remediation(
        human="""
            Open the Web analytics health page. Web analytics excludes any $pageview whose $session_id is
            empty or not a UUID, so those events undercount your visitor and session counts. This usually
            comes from events sent server-side or through a third-party pipeline that omits $session_id.
            Attach a valid session id (a UUIDv7 if you can) to those events. See
            https://posthog.com/docs/data/sessions#custom-session-ids.
        """,
        agent="""
            Use `execute-sql` to size the gap (`SELECT countIf(toUUIDOrNull(JSONExtractString(properties,
            '$session_id')) IS NULL) AS missing, count() AS total FROM events WHERE event = '$pageview' AND
            timestamp > now() - INTERVAL 7 DAY`). Then fix it in the user's codebase: find where $pageview
            events are produced outside posthog-js — server-side SDK calls or a third-party pipeline — and set
            a valid `$session_id` (a UUID, ideally UUIDv7) on each event. Use `docs-search` for the custom
            session id docs. Once the events carry a valid session id, the issue resolves on the next check run.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        return AlertContent(
            title="Pageviews missing a session id",
            summary=issue.payload.get("reason", "$pageview events arrive without a valid $session_id"),
            link="/web/health",
        )

    @classmethod
    def render_signal(cls, issue: HealthIssue) -> SignalContent | None:
        title = "Pageviews missing a session id"
        summary = issue.payload.get("reason", "$pageview events arrive without a valid $session_id.")
        return SignalContent(
            description=(
                f"A meaningful share of this project's `$pageview` events arrive without a valid `$session_id` "
                f"over the last {MISSING_SESSION_ID_LOOKBACK_DAYS} days. Web analytics excludes any event whose "
                "`$session_id` is empty or not a UUID, so visitor and session counts come in under the real "
                "numbers while the raw events stay queryable in product analytics. This usually means events are "
                "sent server-side or through a third-party pipeline that omits `$session_id`. Recommend attaching "
                "a valid session id (a UUID) to those events."
            ),
            weight=_SEVERITY_WEIGHT[issue.severity],
            extra=build_signal_extra(issue, title=title, summary=summary, link="/web/health"),
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        rows = execute_clickhouse_health_team_query(
            MISSING_SESSION_ID_SQL,
            team_ids=team_ids,
            lookback_days=MISSING_SESSION_ID_LOOKBACK_DAYS,
            params={
                "threshold": MISSING_SESSION_ID_THRESHOLD,
                "min_pageviews": MISSING_SESSION_ID_MIN_PAGEVIEWS,
            },
        )

        issues: dict[int, list[HealthCheckResult]] = {}
        for team_id, total_pageviews, missing_session_id in rows:
            share = missing_session_id / total_pageviews
            issues[team_id] = [
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING,
                    payload={
                        "reason": (
                            f"{share:.1%} of $pageview events ({missing_session_id} of {total_pageviews}) "
                            f"arrived without a valid $session_id in last {MISSING_SESSION_ID_LOOKBACK_DAYS} days"
                        )
                    },
                    hash_keys=[],
                )
            ]

        return issues
