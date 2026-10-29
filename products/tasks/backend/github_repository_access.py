import logging
from collections.abc import Iterable

from posthog.egress.limiter.policies import Priority
from posthog.integrations import IntegrationManager
from posthog.models.integration import GitHubIntegration

logger = logging.getLogger(__name__)


def inaccessible_repositories_via_integration(
    team_id: int, integration_id: int, full_names: Iterable[str]
) -> list[str]:
    names = list(full_names)
    integration = IntegrationManager.github.oauth.get_many(team_id, [integration_id]).get(integration_id)
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
