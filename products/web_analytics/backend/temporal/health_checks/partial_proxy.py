import re
from collections import defaultdict

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

PARTIAL_PROXY_LOOKBACK_DAYS = 7
MIN_EVENTS_PER_HOST = 50
MAX_HOSTS_IN_PAYLOAD = 10
MAX_HOST_LENGTH = 253

_HOST_RE = re.compile(r"^[A-Za-z0-9._\-]+(?::\d{1,5})?$")


def _is_valid_host(host: str) -> bool:
    if not host or len(host) > MAX_HOST_LENGTH:
        return False
    return bool(_HOST_RE.fullmatch(host))


PARTIAL_PROXY_SQL = """
SELECT
    team_id,
    JSONExtractString(properties, '$host') AS host,
    countIf(JSONHas(properties, '$lib_custom_api_host')) > 0 AS has_proxy,
    count() AS event_count
FROM events
WHERE team_id IN %(team_ids)s
  AND event IN ('$pageview', '$screen')
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
  AND JSONExtractString(properties, '$host') != ''
GROUP BY team_id, host
HAVING event_count >= %(min_events_per_host)s
ORDER BY event_count DESC
LIMIT %(max_hosts_per_bucket)s BY team_id, has_proxy
"""


class PartialProxyCheck(HealthCheck):
    name = "partial_proxy"
    kind = "partial_proxy"
    owner = JobOwners.TEAM_WEB_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "45 6 * * *"
    active_since_days = 30
    remediation = Remediation(
        human="""
            Open the Web analytics health page — it lists the hostnames that aren't going through a proxy.
            For each of those, point the SDK's `api_host` at your reverse proxy (the same proxy your other
            domains already use) and redeploy, so every domain ingests through your own domain.
        """,
        agent="""
            Read this issue with `health-issues-get` — the payload's `unproxied_hosts` lists the domains to
            fix — and use `execute-sql` to verify coverage per host (group recent $pageview events by
            `properties.$host` and whether `properties.$lib_custom_api_host` is set). Check existing proxies
            with `proxy-list`. Then fix it in the user's codebase: for the deployments serving those hosts,
            set `api_host` in the `posthog.init` call to the existing reverse proxy URL (adding the proxy
            rewrite/route, or a new managed proxy via `proxy-create`, if that host doesn't have one yet).
            Use `docs-search` for the reverse proxy guide. Once all hosts are proxied, the issue clears on
            the next check run.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        unproxied = issue.payload.get("unproxied_hosts") or []
        summary = (
            f"{len(unproxied)} host(s) lack a reverse proxy: {', '.join(unproxied[:3])}"
            if unproxied
            else issue.payload.get("reason", "Reverse proxy is only configured on some hostnames")
        )
        return AlertContent(
            title="Partial reverse-proxy coverage",
            summary=summary,
            link="/web/health",
        )

    @classmethod
    def render_signal(cls, issue: HealthIssue) -> SignalContent | None:
        unproxied = issue.payload.get("unproxied_hosts") or []
        hosts_clause = f" ({', '.join(unproxied[:5])})" if unproxied else ""
        title = "Partial reverse-proxy coverage"
        summary = (
            f"{len(unproxied)} host(s) lack a reverse proxy{hosts_clause}"
            if unproxied
            else issue.payload.get("reason", "Reverse proxy is only configured on some hostnames.")
        )
        return SignalContent(
            description=(
                f"This project sends events through a reverse proxy on some hostnames but not others — "
                f"{len(unproxied)} host(s) are unproxied{hosts_clause}. Traffic from the unproxied hosts is "
                "more likely to be blocked by ad blockers and to have inaccurate geolocation, so analytics "
                "will be inconsistent across your domains. Recommend extending the reverse proxy to every host."
            ),
            weight=_SEVERITY_WEIGHT[issue.severity],
            extra=build_signal_extra(issue, title=title, summary=summary, link="/web/health"),
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        rows = execute_clickhouse_health_team_query(
            PARTIAL_PROXY_SQL,
            team_ids=team_ids,
            lookback_days=PARTIAL_PROXY_LOOKBACK_DAYS,
            params={
                "min_events_per_host": MIN_EVENTS_PER_HOST,
                "max_hosts_per_bucket": MAX_HOSTS_IN_PAYLOAD,
            },
        )

        proxied_by_team: dict[int, list[str]] = defaultdict(list)
        unproxied_by_team: dict[int, list[str]] = defaultdict(list)
        for team_id, host, has_proxy, _event_count in rows:
            if not _is_valid_host(host):
                continue
            if has_proxy:
                proxied_by_team[team_id].append(host)
            else:
                unproxied_by_team[team_id].append(host)

        issues: dict[int, list[HealthCheckResult]] = {}
        for team_id, proxied in proxied_by_team.items():
            unproxied = unproxied_by_team.get(team_id, [])
            if not unproxied:
                continue
            issues[team_id] = [
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING,
                    payload={
                        "reason": "Reverse proxy is only configured on some hostnames. "
                        "Traffic from unproxied hosts is more likely to be blocked or have inaccurate geolocation.",
                        "proxied_hosts": sorted(proxied),
                        "unproxied_hosts": sorted(unproxied),
                    },
                    hash_keys=[],
                )
            ]

        return issues
