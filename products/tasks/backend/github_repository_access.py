import logging
from collections.abc import Iterable, Sequence

from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY
from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, GitHubIntegration, Integration

logger = logging.getLogger(__name__)


def inaccessible_repositories_via_integration(
    team_id: int, integration_id: int, full_names: Iterable[str]
) -> list[str]:
    names = list(full_names)
    integration = Integration.objects.filter(team_id=team_id, kind="github", id=integration_id).first()
    if integration is None:
        return names
    try:
        repositories = GitHubIntegration(
            integration, source="tasks", priority=Priority.CRITICAL
        ).list_all_cached_repositories()
    except Exception:
        logger.warning(
            "github_repository_access_check_unavailable",
            exc_info=True,
            extra={"team_id": team_id, "integration_id": integration_id},
        )
        return names
    accessible = {str(repo.get("full_name", "")).lower() for repo in repositories if isinstance(repo, dict)}
    return [full_name for full_name in names if full_name.strip().lower() not in accessible]


def usable_team_github_integrations(team_id: int) -> list[Integration]:
    """The team's GitHub integrations a task can get a token from, oldest first."""
    return list(
        Integration.objects.filter(team_id=team_id, kind="github")
        .exclude(errors=ERROR_TOKEN_REFRESH_FAILED)
        .exclude(config__has_key=INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY)
        .order_by("id")
    )


def first_integration_reaching_repositories(
    integrations: Sequence[Integration], repositories: Iterable[str]
) -> Integration | None:
    """The first integration whose stored repository list holds every repository."""
    wanted = {repository.lower() for repository in repositories}
    return next((integration for integration in integrations if wanted <= _stored_repository_names(integration)), None)


def repositories_no_team_installation_reaches(team_id: int, full_names: Iterable[str]) -> list[str]:
    """The repositories that no usable GitHub installation of the team lists."""
    reachable: set[str] = set()
    for integration in usable_team_github_integrations(team_id):
        reachable |= _stored_repository_names(integration)
    return [full_name for full_name in full_names if full_name.lower() not in reachable]


def _stored_repository_names(integration: Integration) -> set[str]:
    # Never calls GitHub: callers run inside transactions that hold row locks.
    stored = GitHubIntegration(integration, source="tasks", priority=Priority.CRITICAL).list_all_cached_repositories(
        allow_refresh=False
    )
    return {str(repository["full_name"]).lower() for repository in stored}
