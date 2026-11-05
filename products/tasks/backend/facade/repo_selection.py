"""
Facade re-exports for repository selection.

The repo-selection agent picks a GitHub repository for a task given free-text context. Its
result type and errors are framework-free; other products call ``select_repository`` and
handle the typed outcomes.
"""

from posthog.models.team.team import Team

from products.tasks.backend.github_repository_access import inaccessible_repositories_via_integration
from products.tasks.backend.logic.repo_selection import (
    REPO_SELECTION_DUMMY_REPOSITORY,
    RepoSelectionRejectedError,
    RepoSelectionResult,
    RepoSelectionUnavailableError,
    RepoSelectionUsageLimitError,
    filter_repository_candidates_for_sources,
    list_team_connected_repositories,
    resolve_team_github_integration,
    select_repository,
)
from products.tasks.backend.temporal.process_task.utils import get_github_token


def repository_accessible_via_integration(team_id: int, integration_id: int, repository: str) -> bool:
    return not inaccessible_repositories_via_integration(team_id, integration_id, [repository])


def team_repository_names(
    team_id: int, *, team: Team | None = None, refresh_stale_snapshot: bool = True
) -> dict[str, str] | None:
    """The repositories the team's own GitHub installation can reach, keyed by lowercased `owner/repo`.

    Each value keeps GitHub's casing, for display. Returns None when the team has no GitHub installation.
    `team_only` because callers show these names to any project member and run work as the installation's
    bot, so a member's personal connection must not answer for the team. Callers apply their own precedence
    to pick one repository from the result.

    With `refresh_stale_snapshot=False`, a stale snapshot is used as it is, and GitHub is called only when no
    snapshot exists yet. A refresh lists every page of the installation inside the request.
    """
    github = resolve_team_github_integration(team_id, team=team, team_only=True)
    if github is None:
        return None
    repositories = (
        None if refresh_stale_snapshot else github.list_all_cached_repositories(max_repos=1000, allow_refresh=False)
    ) or github.list_all_cached_repositories(max_repos=1000)
    return {full_name.lower(): full_name for repo in repositories if (full_name := repo.get("full_name"))}


def resolve_team_github_integration_id(team_id: int) -> int | None:
    integration = resolve_team_github_integration(team_id, team_only=True)
    return integration.integration.id if integration is not None else None


__all__ = [
    "REPO_SELECTION_DUMMY_REPOSITORY",
    "RepoSelectionRejectedError",
    "RepoSelectionResult",
    "RepoSelectionUnavailableError",
    "RepoSelectionUsageLimitError",
    "get_github_token",
    "filter_repository_candidates_for_sources",
    "list_team_connected_repositories",
    "repository_accessible_via_integration",
    "resolve_team_github_integration",
    "resolve_team_github_integration_id",
    "select_repository",
    "team_repository_names",
]
