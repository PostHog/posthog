from django.db.models import Q

from posthog.dags.common.owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.models.team import Team
from posthog.temporal.health_checks.detectors import DEFAULT_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import AlertContent, HealthCheck, Remediation
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
            This is a PostHog project setting (the team's `app_urls`), not a codebase change — and you can
            fix it directly. Use `execute-sql` on recent $pageview events' `properties.$host` /
            `properties.$current_url` to list the domains the project actually sends events from
            (`SELECT properties.$host, count() FROM events WHERE event = '$pageview' AND timestamp > now()
            - INTERVAL 7 DAY GROUP BY 1 ORDER BY 2 DESC`). Then call `project-get` to read the current
            settings and `project-settings-update` to set `app_urls` to those domains (append, don't
            clobber existing entries). The issue resolves once at least one authorized URL is set.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        return AlertContent(
            title="No authorized URLs configured",
            summary=issue.payload.get("reason", "Authorized URLs are not set"),
            link="/web/health",
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
