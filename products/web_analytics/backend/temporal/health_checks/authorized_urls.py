from django.db.models import Q

from posthog.dags.common.owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.models.team import Team
from posthog.temporal.health_checks.detectors import DEFAULT_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import (
    _SEVERITY_WEIGHT,
    AlertContent,
    HealthCheck,
    Remediation,
    SignalContent,
    build_signal_extra,
)
from posthog.temporal.health_checks.models import HealthCheckResult


class AuthorizedUrlsCheck(HealthCheck):
    name = "authorized_urls"
    kind = "authorized_urls"
    owner = JobOwners.TEAM_WEB_ANALYTICS
    policy = DEFAULT_EXECUTION_POLICY
    schedule = "15 8 * * *"
    active_since_days = 30
    remediation = Remediation(
        human="""
            Go to Project settings → Authorized URLs (also reachable from the Web analytics health page)
            and add each domain you run on, including staging and any subdomains (for example
            https://example.com and https://app.example.com). Wildcards are supported for dynamic
            subdomains.
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
            entries). Never add an event-derived domain without that explicit confirmation. The issue
            resolves once at least one authorized URL is set.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        return AlertContent(
            title="No authorized URLs configured",
            summary=issue.payload.get("reason", "Authorized URLs are not set"),
            link="/web/health",
        )

    @classmethod
    def render_signal(cls, issue: HealthIssue) -> SignalContent | None:
        title = "No authorized URLs configured"
        summary = issue.payload.get("reason", "No authorized URLs configured. Some filters won't work correctly.")
        return SignalContent(
            description=(
                "This project has no authorized URLs (app URLs) configured. Without them, the toolbar can't "
                "launch on your site and some web-analytics filters won't work correctly. Recommend adding your "
                "site's domains under Project settings → Authorized URLs."
            ),
            weight=_SEVERITY_WEIGHT[issue.severity],
            extra=build_signal_extra(issue, title=title, summary=summary, link="/web/health"),
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        teams_missing_urls = (
            Team.objects.filter(
                id__in=team_ids,
            )
            .filter(Q(app_urls=[]) | Q(app_urls__isnull=True))
            .values_list("id", flat=True)
        )

        issues: dict[int, list[HealthCheckResult]] = {}
        for team_id in teams_missing_urls:
            issues[team_id] = [
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING,
                    payload={"reason": "No authorized URLs configured. Some filters won't work correctly."},
                    hash_keys=[],
                )
            ]

        return issues
