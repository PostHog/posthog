from django.core.cache import cache

import structlog

from products.tasks.backend.facade import repo_selection
from products.wizard.backend.facade.errors import MissingGitHubIntegrationError, RepositoryNotAccessibleError
from products.wizard.backend.logic.runs.validation import validate_git_repository_name
from products.wizard.backend.observability.tracing import wizard_span

logger = structlog.get_logger(__name__)

REPOSITORY_CACHE_MIN_REFRESH_INTERVAL_SECONDS = 60


@wizard_span("wizard.repository.authorize")
def authorize_git_repository_access(team_id: int, repository: str) -> int:
    validate_git_repository_name(repository)

    integration_id = repo_selection.resolve_team_github_integration_id(team_id)
    if integration_id is None:
        raise MissingGitHubIntegrationError

    if not repo_selection.repository_accessible_via_integration(team_id, integration_id, repository):
        raise RepositoryNotAccessibleError

    return integration_id


def refresh_repository_cache(team_id: int) -> bool:
    """
    Sync the project's cached GitHub repository list. Returns whether a sync ran and succeeded.

    The cached list can miss a repository added to the GitHub App a moment ago.
    """
    github = repo_selection.resolve_team_github_integration(team_id, team_only=True)
    if github is None:
        return False

    # A sync pages through every repository of the installation. One reservation per interval stops concurrent
    # misses, and repeated failures, from each starting their own sync.
    reservation_key = f"wizard:repository-cache-refresh:{github.integration.id}"
    if not cache.add(reservation_key, 1, timeout=REPOSITORY_CACHE_MIN_REFRESH_INTERVAL_SECONDS):
        return False

    try:
        github.sync_repository_cache(min_refresh_interval_seconds=REPOSITORY_CACHE_MIN_REFRESH_INTERVAL_SECONDS)
    except Exception:
        logger.warning(
            "wizard_repository_cache_refresh_failed",
            exc_info=True,
            team_id=team_id,
            integration_id=github.integration.id,
        )
        return False
    return True
