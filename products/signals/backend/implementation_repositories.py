"""Extra repositories that self-driving implementation tasks may read and write.

A project lists them in `SignalTeamConfig.implementation_repositories`. They widen the run's GitHub
token only: the run clones the selected repository and opens its pull request there, as before.
"""

import re
from collections.abc import Iterable, Sequence

import structlog

from posthog.egress.limiter.policies import Priority
from posthog.integrations import IntegrationManager
from posthog.models.integration import GitHubIntegration

from products.signals.backend.models import SignalTeamConfig

logger = structlog.get_logger(__name__)

# Each entry widens every implementation token in the project, so the list stays short.
MAX_IMPLEMENTATION_REPOSITORIES = 20

_REPOSITORY_PATTERN = re.compile(r"^[a-z0-9._-]+/[a-z0-9._-]+$")


class InvalidImplementationRepository(ValueError):
    pass


def normalize_implementation_repositories(values: Iterable[str]) -> list[str]:
    """Lowercased, deduplicated "organization/repository" names in input order."""
    normalized: list[str] = []
    for value in values:
        repository = str(value).strip().lower()
        if not _REPOSITORY_PATTERN.match(repository):
            raise InvalidImplementationRepository(
                f"'{value}' is not a GitHub repository. Use the 'organization/repository' form."
            )
        if repository not in normalized:
            normalized.append(repository)
    if len(normalized) > MAX_IMPLEMENTATION_REPOSITORIES:
        raise InvalidImplementationRepository(
            f"Too many repositories ({len(normalized)}). The maximum is {MAX_IMPLEMENTATION_REPOSITORIES}."
        )
    return normalized


def repositories_missing_from_installations(team_id: int, repositories: Sequence[str]) -> list[str]:
    """The entries of `repositories` that no team-level GitHub installation of the project can reach.

    Only team-level installations count, because the implementation token is minted from one. A
    personal connection could name repositories the project never connected.
    """
    if not repositories:
        return []
    reachable: set[str] = set()
    for integration in IntegrationManager.github.oauth.list(team_id):
        github = GitHubIntegration(integration, source="signals_implementation_repositories", priority=Priority.NORMAL)
        try:
            cached = github.list_all_cached_repositories()
        except Exception:
            logger.warning(
                "implementation_repositories_installation_unreadable",
                team_id=team_id,
                integration_id=integration.id,
                exc_info=True,
            )
            continue
        reachable.update(str(repository.get("full_name", "")).lower() for repository in cached)
    return [repository for repository in repositories if repository not in reachable]


def implementation_access_repositories(team_id: int, repository: str) -> list[str]:
    """The configured repositories an implementation task on `repository` gets, without `repository`.

    Only entries with the same owner as `repository` apply. One GitHub installation covers one
    account, so an entry from another owner is outside the installation the task's token comes from.
    """
    owner = repository.lower().partition("/")[0]
    configured = (
        SignalTeamConfig.objects.filter(team_id=team_id).values_list("implementation_repositories", flat=True).first()
    )
    if not isinstance(configured, list):
        return []
    return [
        entry
        for entry in configured
        if isinstance(entry, str) and entry.partition("/")[0] == owner and entry != repository.lower()
    ]
