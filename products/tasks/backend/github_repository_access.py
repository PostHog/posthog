import logging
from collections.abc import Iterable

from posthog.models.integration import GitHubIntegration, Integration

logger = logging.getLogger(__name__)


def inaccessible_repositories_via_integration(
    team_id: int, integration_id: int, full_names: Iterable[str]
) -> list[str]:
    names = list(full_names)
    integration = Integration.objects.filter(team_id=team_id, kind="github", id=integration_id).first()
    if integration is None:
        return names
    try:
        repositories = GitHubIntegration(integration).list_all_cached_repositories()
    except Exception:
        logger.warning(
            "github_repository_access_check_unavailable",
            exc_info=True,
            extra={"team_id": team_id, "integration_id": integration_id},
        )
        return names
    accessible = {str(repo.get("full_name", "")).lower() for repo in repositories if isinstance(repo, dict)}
    return [full_name for full_name in names if full_name.strip().lower() not in accessible]


def _integration_account_name(integration: Integration) -> str:
    account = integration.config.get("account")
    name = account.get("name") if isinstance(account, dict) else None
    return str(name).strip().lower() if isinstance(name, str) else ""


def _cached_repository_names(integration: Integration) -> set[str]:
    """Repository full names already stored on the row — a pure cache read, never a GitHub call."""
    try:
        repositories = GitHubIntegration(integration).list_all_cached_repositories(allow_refresh=False)
    except Exception:
        logger.warning(
            "github_integration_repository_cache_unavailable",
            exc_info=True,
            extra={"integration_id": integration.id},
        )
        return set()
    return {
        str(repo.get("full_name", "")).strip().lower()
        for repo in repositories
        if isinstance(repo, dict) and repo.get("full_name")
    }


def select_integration_for_repository(
    integrations: Iterable[Integration], repository: str | None
) -> Integration | None:
    """Pick the connected installation that can reach ``repository``.

    A project can connect several GitHub App installations. Taking the first one gives the
    provisioner a valid token minted for the wrong account, and every clone and push then
    fails. Match the repository owner against the installation account first, then against
    the stored repository cache, which still resolves an installation whose account name was
    never filled in. A project with one installation keeps the token it always got.
    """
    candidates = list(integrations)
    if not candidates:
        return None
    if not repository:
        return candidates[0]

    full_name = repository.strip().lower()
    owner = full_name.split("/")[0]
    for integration in candidates:
        if _integration_account_name(integration) == owner:
            return integration
    for integration in candidates:
        if full_name in _cached_repository_names(integration):
            return integration
    if len(candidates) > 1:
        # The fallback keeps a project whose installation data is incomplete working as before,
        # but the token it produces can belong to another account, so record the guess.
        logger.warning(
            "github_integration_repository_owner_unmatched",
            extra={"repository": full_name, "candidate_integration_ids": [i.id for i in candidates]},
        )
    return candidates[0]
