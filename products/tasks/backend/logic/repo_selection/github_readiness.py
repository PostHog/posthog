from django.db.models import Case, IntegerField, Value, When

from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.integration.github_readiness import (
    GitHubAccessUnavailable,
    GitHubReadiness,
    GitHubReadinessStatus,
    github_readiness,
)
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration


def get_team_github_readiness(team_id: int, *, verify: bool = False, team_only: bool = False) -> GitHubReadiness:
    candidates: list[GitHubIntegrationBase] = [
        GitHubIntegration(row, source="github_readiness", priority=Priority.BATCH)
        for row in Integration.objects.filter(team_id=team_id, kind="github").order_by(
            "config__account__type", "created_at", "id"
        )
    ]
    if not team_only:
        owner_ids = OrganizationMembership.objects.filter(
            organization_id=Team.objects.values_list("organization_id", flat=True).get(pk=team_id),
            level=OrganizationMembership.Level.OWNER,
            user__is_active=True,
        ).values_list("user_id", flat=True)
        candidates.extend(
            UserGitHubIntegration(row, source="github_readiness", priority=Priority.BATCH)
            for row in UserIntegration.objects.filter(kind="github", user_id__in=owner_ids)
            .annotate(
                _is_org_account=Case(
                    When(config__account__type="User", then=Value(0)), default=Value(1), output_field=IntegerField()
                )
            )
            .order_by("_is_org_account", "-created_at", "-id")
        )
    blocked = GitHubReadiness(status=GitHubReadinessStatus.NOT_CONNECTED)
    for github in candidates:
        readiness = github_readiness(github, verify=verify)
        if readiness.status == GitHubReadinessStatus.READY:
            return readiness
        if blocked.status == GitHubReadinessStatus.NOT_CONNECTED:
            blocked = readiness
    return blocked


def require_github_readiness(team_id: int, *, verify: bool = True) -> None:
    readiness = get_team_github_readiness(team_id, verify=verify)
    if readiness.status != GitHubReadinessStatus.READY:
        raise GitHubAccessUnavailable(readiness.status)
