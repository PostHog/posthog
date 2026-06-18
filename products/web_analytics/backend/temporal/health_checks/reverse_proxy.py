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

REVERSE_PROXY_LOOKBACK_DAYS = 1
REVERSE_PROXY_SQL = """
SELECT team_id
FROM events
WHERE team_id IN %(team_ids)s
  AND event IN ('$pageview', '$screen')
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
GROUP BY team_id
HAVING countIf(JSONHas(properties, '$lib_custom_api_host')) = 0
"""


class ReverseProxyCheck(HealthCheck):
    name = "reverse_proxy"
    kind = "reverse_proxy"
    owner = JobOwners.TEAM_WEB_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "30 6 * * *"
    active_since_days = 30
    remediation = Remediation(
        human="""
            Set up a reverse proxy that forwards a path on your own domain (e.g. https://ph.example.com or
            https://example.com/ingest) to PostHog, then point your SDK's `api_host` at that proxy URL and
            redeploy. PostHog supports several options (managed reverse proxy, Cloudflare, Vercel, AWS
            CloudFront, nginx, etc.).
        """,
        agent="""
            Confirm traffic isn't proxied with `execute-sql` (check recent events'
            `properties.$lib_custom_api_host`). Then either stand up a PostHog-managed reverse proxy with
            `proxy-create` (use `proxy-list` / `proxy-diagnose` to get the CNAME target and check
            provisioning) and have the user add the DNS record, or implement a proxy in the user's
            codebase — add the rewrite/route for their stack (e.g. `rewrites` in next.config.js, a
            `vercel.json` route, an nginx `location` block, or a Cloudflare worker). Either way, set
            `api_host` (and `ui_host`) in the `posthog.init` call to the proxied URL and redeploy. Use
            `docs-search` for the reverse proxy guide for their framework. Once proxied events arrive, the
            issue resolves on the next check run.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        return AlertContent(
            title="No reverse proxy detected",
            summary=issue.payload.get("reason", "Ad blockers may affect tracking accuracy"),
            link="/web/health",
        )

    @classmethod
    def render_signal(cls, issue: HealthIssue) -> SignalContent | None:
        title = "No reverse proxy detected"
        summary = issue.payload.get("reason", "Ad blockers may affect tracking accuracy.")
        return SignalContent(
            description=(
                "PostHog isn't receiving events through a reverse proxy for this project. "
                "Without one, ad blockers can silently drop a meaningful share of "
                "`$pageview` / `$screen` events, undercounting traffic and skewing web analytics. "
                "Recommend serving capture from a first-party domain via a reverse proxy."
            ),
            weight=_SEVERITY_WEIGHT[issue.severity],
            extra=build_signal_extra(issue, title=title, summary=summary, link="/web/health"),
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        rows = execute_clickhouse_health_team_query(
            REVERSE_PROXY_SQL,
            team_ids=team_ids,
            lookback_days=REVERSE_PROXY_LOOKBACK_DAYS,
        )

        issues: dict[int, list[HealthCheckResult]] = {}
        for (team_id,) in rows:
            issues[team_id] = [
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING,
                    payload={"reason": "No reverse proxy detected. Ad blockers may affect tracking accuracy."},
                    hash_keys=[],
                )
            ]

        return issues
