import logging

from django.core.cache import cache

from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration, Integration

from products.tasks.backend.facade import repo_selection
from products.wizard.backend.facade.errors import MissingGitHubIntegrationError, RepositoryNotAccessibleError
from products.wizard.backend.logic.runs.validation import validate_git_repository_name
from products.wizard.backend.observability.tracing import wizard_span

logger = logging.getLogger(__name__)

# The repository list is cached, so a repository added to the GitHub App a moment ago can be missing from it.
REPOSITORY_CACHE_MIN_REFRESH_INTERVAL_SECONDS = 60


@wizard_span("wizard.repository.authorize")
def authorize_git_repository_access(team_id: int, repository: str, *, refresh_cache_on_miss: bool = False) -> int:
    validate_git_repository_name(repository)

    integration_id = repo_selection.resolve_team_github_integration_id(team_id)
    if integration_id is None:
        raise MissingGitHubIntegrationError

    if repo_selection.repository_accessible_via_integration(team_id, integration_id, repository):
        return integration_id

    if refresh_cache_on_miss and _refresh_repository_cache(team_id, integration_id):
        if repo_selection.repository_accessible_via_integration(team_id, integration_id, repository):
            return integration_id

    raise RepositoryNotAccessibleError


def _refresh_repository_cache(team_id: int, integration_id: int) -> bool:
    # A sync pages through every repository of the installation. One reservation per interval stops concurrent
    # misses, and repeated failures, from each starting their own sync.
    reservation_key = f"wizard:repository-cache-refresh:{integration_id}"
    if not cache.add(reservation_key, 1, timeout=REPOSITORY_CACHE_MIN_REFRESH_INTERVAL_SECONDS):
        return False

    integration = Integration.objects.filter(team_id=team_id, id=integration_id, kind="github").first()
    if integration is None:
        return False
    try:
        GitHubIntegration(integration, source="wizard", priority=Priority.CRITICAL).sync_repository_cache(
            min_refresh_interval_seconds=REPOSITORY_CACHE_MIN_REFRESH_INTERVAL_SECONDS
        )
    except Exception:
        logger.warning(
            "wizard_repository_cache_refresh_failed",
            exc_info=True,
            extra={"team_id": team_id, "integration_id": integration_id},
        )
        return False
    return True
