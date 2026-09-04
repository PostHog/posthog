from urllib.parse import urlparse

from posthog.api.utils import hostname_in_allowed_url_list
from posthog.clickhouse.query_tagging import Product
from posthog.job_owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.models.team import Team
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

MISSING_URLS = "missing_urls"
DOMAIN_MISMATCH = "domain_mismatch"

MISMATCH_LOOKBACK_DAYS = 7
# Below this, one crawler or one internal tester is enough to look like the whole site.
MISMATCH_MIN_PAGEVIEWS = 100
# How many hosts to rank per team. The tail below the last one is what the coverage rule bounds.
MISMATCH_TOP_HOSTS = 20
# Only judge a team whose ranked hosts hold nearly all its pageviews. A long tail of hosts
# (wildcard subdomains, for example) can hide a match outside the ranking.
MISMATCH_MIN_COVERAGE = 0.99
# How many hosts to name in the payload the user reads.
MISMATCH_REPORTED_HOSTS = 5

MISMATCH_SQL = """
SELECT team_id, host, pageviews, team_pageviews
FROM (
    SELECT
        team_id,
        JSONExtractString(properties, '$host') AS host,
        count() AS pageviews,
        sum(count()) OVER (PARTITION BY team_id) AS team_pageviews,
        row_number() OVER (PARTITION BY team_id ORDER BY count() DESC) AS host_rank
    FROM events
    WHERE team_id IN %(team_ids)s
      AND event = '$pageview'
      AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
    GROUP BY team_id, host
)
WHERE host != '' AND host_rank <= %(top_hosts)s
"""


def _normalize_host(host: str) -> str | None:
    """Drop the port and case from a `$host` value so it compares like a parsed app URL."""
    try:
        return urlparse(f"//{host}").hostname
    except ValueError:
        return None


class AuthorizedUrlsCheck(HealthCheck):
    name = "authorized_urls"
    kind = "authorized_urls"
    owner = JobOwners.TEAM_WEB_ANALYTICS
    product = Product.WEB_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "15 8 * * *"
    active_since_days = 30
    remediation = Remediation(
        human="""
            Go to Project settings → Authorized URLs (also reachable from the Web analytics health page)
            and add each domain you run on, including staging and any subdomains (for example
            https://example.com and https://app.example.com). Wildcards are supported for dynamic
            subdomains.

            If the issue says your authorized URLs no longer match your traffic, you probably moved the
            site to a new domain. Adding the new domain here and removing the old one is the whole
            migration, because nothing else in PostHog is tied to a domain. Check the replay domains in
            Session replay settings too, if you set any.
        """,
        agent="""
            This is a PostHog project setting (the team's `app_urls`), not a codebase change. `app_urls` is
            a security boundary — it's the allowlist the toolbar uses to decide which domains it may redirect
            to — so never populate it from event data unattended. Use `execute-sql` on recent $pageview
            events' `properties.$host` / `properties.$current_url` for DISCOVERY ONLY (`SELECT
            properties.$host, count() FROM events WHERE event = '$pageview' AND timestamp > now() - INTERVAL
            7 DAY GROUP BY 1 ORDER BY 2 DESC`). Treat every host you find as untrusted: anyone who knows the
            project's public token can send spoofed $pageview events with an arbitrary `$host`, so a domain
            showing up here is NOT proof the user owns it. Present the discovered domains and have the user
            confirm which ones they actually own; then call `project-get` to read the current settings and
            `project-settings-update` to append only the user-confirmed domains (don't clobber existing
            entries). Never add an event-derived domain without that explicit confirmation.

            The issue payload's `reason_code` says which case you're in. `missing_urls` resolves once at
            least one authorized URL is set. `domain_mismatch` means authorized URLs exist but no recent
            pageview came from them — the payload carries `configured_urls` and the observed
            `unauthorized_hosts`. Ask the user which of the observed hosts they own, add those, and offer to
            remove the entries that no longer receive traffic. Also ask whether `recording_domains` (Session
            replay settings) names the old domain, because replay capture uses its own list.
        """,
    )

    @classmethod
    def _is_mismatch(cls, issue: HealthIssue) -> bool:
        return issue.payload.get("reason_code") == DOMAIN_MISMATCH

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        if cls._is_mismatch(issue):
            return AlertContent(
                title="Authorized URLs don't match your traffic",
                summary=issue.payload.get("reason", "No recent pageviews come from your authorized URLs"),
                link="/web/health",
            )
        return AlertContent(
            title="No authorized URLs configured",
            summary=issue.payload.get("reason", "Authorized URLs are not set"),
            link="/web/health",
        )

    @classmethod
    def render_signal(cls, issue: HealthIssue) -> SignalContent | None:
        if cls._is_mismatch(issue):
            title = "Authorized URLs don't match your traffic"
            summary = issue.payload.get("reason", "No recent pageviews come from your authorized URLs.")
            description = (
                f"This project has authorized URLs configured, but none of the pageviews from the last "
                f"{MISMATCH_LOOKBACK_DAYS} days come from them. This is what a website domain change looks "
                "like: the toolbar can't launch, web-analytics domain filters stop matching, and replay may "
                "stop capturing. Nothing else in PostHog is tied to a domain, so the fix is to add the new "
                "domain under Project settings → Authorized URLs (and in Session replay settings, if replay "
                "domains are set). Confirm the domains with the user first, because event hosts can be spoofed."
            )
        else:
            title = "No authorized URLs configured"
            summary = issue.payload.get("reason", "No authorized URLs configured. Some filters won't work correctly.")
            description = (
                "This project has no authorized URLs (app URLs) configured. Without them, the toolbar can't "
                "launch on your site and some web-analytics filters won't work correctly. Recommend adding your "
                "site's domains under Project settings → Authorized URLs."
            )
        return SignalContent(
            description=description,
            weight=_SEVERITY_WEIGHT[issue.severity],
            extra=build_signal_extra(issue, title=title, summary=summary, link="/web/health"),
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        issues: dict[int, list[HealthCheckResult]] = {}
        configured: dict[int, list[str]] = {}

        for team_id, app_urls in Team.objects.filter(id__in=team_ids).values_list("id", "app_urls"):
            if app_urls:
                configured[team_id] = app_urls
            else:
                issues[team_id] = [
                    HealthCheckResult(
                        severity=HealthIssue.Severity.WARNING,
                        payload={
                            "reason": "No authorized URLs configured. Some filters won't work correctly.",
                            "reason_code": MISSING_URLS,
                        },
                        # Keep the empty hash keys the missing-URLs issue has always used, so teams that
                        # already have one don't get it resolved and re-fired.
                        hash_keys=[],
                    )
                ]

        for team_id, result in self._detect_mismatches(configured).items():
            issues[team_id] = [result]

        return issues

    def _detect_mismatches(self, configured: dict[int, list[str]]) -> dict[int, HealthCheckResult]:
        if not configured:
            return {}

        rows = execute_clickhouse_health_team_query(
            MISMATCH_SQL,
            team_ids=sorted(configured),
            lookback_days=MISMATCH_LOOKBACK_DAYS,
            params={"top_hosts": MISMATCH_TOP_HOSTS},
        )

        totals: dict[int, int] = {}
        hosts_by_team: dict[int, list[tuple[str, int]]] = {}
        for team_id, host, pageviews, team_pageviews in rows:
            totals[team_id] = team_pageviews
            hosts_by_team.setdefault(team_id, []).append((host, pageviews))

        results: dict[int, HealthCheckResult] = {}
        for team_id, hosts in hosts_by_team.items():
            total = totals[team_id]
            if total < MISMATCH_MIN_PAGEVIEWS:
                continue
            if sum(pageviews for _, pageviews in hosts) < MISMATCH_MIN_COVERAGE * total:
                continue

            app_urls = configured[team_id]
            if any(hostname_in_allowed_url_list(app_urls, _normalize_host(host)) for host, _ in hosts):
                continue

            ranked = sorted(hosts, key=lambda host_count: host_count[1], reverse=True)
            results[team_id] = HealthCheckResult(
                severity=HealthIssue.Severity.WARNING,
                payload={
                    "reason": (
                        f"No pageviews in the last {MISMATCH_LOOKBACK_DAYS} days come from the authorized URLs. "
                        f"Traffic arrives from {ranked[0][0]} instead."
                    ),
                    "reason_code": DOMAIN_MISMATCH,
                    "lookback_days": MISMATCH_LOOKBACK_DAYS,
                    "configured_urls": app_urls,
                    "unauthorized_hosts": [
                        {"host": host, "pageviews": pageviews} for host, pageviews in ranked[:MISMATCH_REPORTED_HOSTS]
                    ],
                },
                hash_keys=["reason_code"],
            )

        return results
