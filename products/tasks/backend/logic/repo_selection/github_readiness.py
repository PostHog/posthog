from datetime import timedelta

from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.integration.github_readiness import (
    GitHubAccessUnavailable,
    GitHubReadiness,
    GitHubReadinessStatus,
    github_readiness,
)
from posthog.models.team.team import Team

GITHUB_RECOVERY_WINDOW = timedelta(days=7)
GITHUB_RECONNECT_REQUIRED_STATUSES = (
    GitHubReadinessStatus.NOT_CONNECTED,
    GitHubReadinessStatus.RECONNECT_REQUIRED,
    GitHubReadinessStatus.NO_REPOSITORIES,
)


def get_team_github_readiness(team_id: int, *, verify: bool = False, repository: str | None = None) -> GitHubReadiness:
    team_id = Team.objects.values_list("parent_team_id", flat=True).get(id=team_id) or team_id
    candidates: list[GitHubIntegrationBase] = [
        GitHubIntegration(row, source="github_readiness", priority=Priority.BATCH)
        for row in Integration.objects.filter(team_id=team_id, kind="github").order_by(
            "config__account__type", "created_at", "id"
        )
    ]
    blocked = GitHubReadiness(status=GitHubReadinessStatus.NOT_CONNECTED)
    for github in candidates:
        readiness = github_readiness(github, verify=verify, repository=repository)
        if readiness.status == GitHubReadinessStatus.READY:
            if (
                verify
                or repository is None
                or any(
                    repo.get("full_name", "").casefold() == repository.casefold()
                    for repo in github.integration.repository_cache or []
                )
            ):
                return readiness
            readiness = GitHubReadiness(status=GitHubReadinessStatus.NO_REPOSITORIES, integration=github)
        if (
            blocked.status == GitHubReadinessStatus.NOT_CONNECTED
            or readiness.status == GitHubReadinessStatus.TEMPORARILY_UNAVAILABLE
        ):
            blocked = readiness
    return blocked


def require_github_readiness(team_id: int, *, verify: bool = True) -> None:
    readiness = get_team_github_readiness(team_id, verify=verify)
    if readiness.status != GitHubReadinessStatus.READY:
        raise GitHubAccessUnavailable(readiness.status)
