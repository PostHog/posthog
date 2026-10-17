import logging
from collections.abc import Iterable

from django.db.models import QuerySet

from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY
from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, GitHubIntegration, Integration

logger = logging.getLogger(__name__)

_MISS_REFRESH_INTERVAL_SECONDS = 60


def usable_team_github_integrations(team_id: int) -> QuerySet[Integration]:
    """The team's GitHub installations that can still mint a token, in the order the team prefers them."""
    return (
        Integration.objects.filter(team_id=team_id, kind="github")
        # Skip integrations whose installation has been synced and confirmed empty (0 repos)
        .exclude(repository_cache=[], repository_cache_updated_at__isnull=False)
        # Skip installs whose token refresh is permanently failing (uninstalled/suspended on
        # GitHub's side): re-selecting one makes repo discovery storm GitHub with doomed refreshes.
        .exclude(errors=ERROR_TOKEN_REFRESH_FAILED)
        .exclude(config__has_key=INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY)
        # Prioritize orgs vs users (alphabetically), then oldest first
        .order_by("config__account__type", "created_at", "id")
    )


def team_github_integration_for_repositories(team_id: int, repositories: Iterable[str]) -> Integration | None:
    """The first usable team installation that reaches every one of ``repositories``.

    The cache answers first. An installation that has never synced its cache comes next, because its
    access is unknown rather than missing. Only then does GitHub confirm the miss, so a cache that
    predates a repository does not fail task creation.
    """
    wanted = {repository.lower() for repository in repositories}
    integrations = list(usable_team_github_integrations(team_id))
    for integration in integrations:
        if wanted <= _cached_full_names(integration):
            return integration
    unsynced = next((i for i in integrations if i.repository_cache_updated_at is None), None)
    if unsynced is not None:
        return unsynced
    unconfirmed: Integration | None = None
    for integration in integrations:
        refreshed = _refreshed_full_names(integration)
        if refreshed is None:
            unconfirmed = unconfirmed or integration
        elif wanted <= refreshed:
            return integration
    return unconfirmed


def default_team_github_integration(team_id: int, repositories: list[str]) -> Integration | None:
    """The installation a task gets when its caller names none: the one that reaches ``repositories``,
    else the team's first, so a caller that reports access problems at run time keeps doing so."""
    reaching = team_github_integration_for_repositories(team_id, repositories) if repositories else None
    return reaching or Integration.objects.filter(team_id=team_id, kind="github").first()


def _cached_full_names(integration: Integration) -> set[str]:
    github = GitHubIntegration(integration, source="tasks", priority=Priority.CRITICAL)
    return {
        full_name.lower()
        for repo in github.list_all_cached_repositories(allow_refresh=False)
        if (full_name := repo.get("full_name"))
    }


def _refreshed_full_names(integration: Integration) -> set[str] | None:
    github = GitHubIntegration(integration, source="tasks", priority=Priority.CRITICAL)
    try:
        repositories = github.sync_repository_cache(min_refresh_interval_seconds=_MISS_REFRESH_INTERVAL_SECONDS)
    except Exception:
        logger.warning(
            "github_repository_cache_refresh_failed",
            exc_info=True,
            extra={"team_id": integration.team_id, "integration_id": integration.id},
        )
        return None
    return {full_name.lower() for repo in repositories if (full_name := repo.get("full_name"))}


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
