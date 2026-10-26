"""
Facade re-exports for repository selection.

The repo-selection agent picks a GitHub repository for a task given free-text context. Its
result type and errors are framework-free; other products call ``select_repository`` and
handle the typed outcomes.
"""

from typing import Literal

from products.tasks.backend.github_repository_access import inaccessible_repositories_via_integration
from products.tasks.backend.logic.repo_selection import (
    REPO_SELECTION_DUMMY_REPOSITORY,
    RepoSelectionRejectedError,
    RepoSelectionResult,
    RepoSelectionUnavailableError,
    RepoSelectionUsageLimitError,
    list_team_connected_repositories,
    resolve_team_github_integration,
    select_repository,
)
from products.tasks.backend.temporal.process_task.utils import get_github_token


def repository_accessible_via_integration(team_id: int, integration_id: int, repository: str) -> bool:
    return not inaccessible_repositories_via_integration(team_id, integration_id, [repository])


class RepositoryCommitError(Exception):
    """A repository or ref that a caller supplied cannot be used. ``code`` is safe to show to the caller."""

    def __init__(self, code: Literal["no_github_integration", "repository_inaccessible", "invalid_ref"]) -> None:
        super().__init__(code)
        self.code = code


def resolve_repository_commit(team_id: int, user_id: int, repository: str, ref: str | None) -> str:
    """Resolve ``ref`` (default branch when ``None``) in ``repository`` to a full commit SHA.

    Uses the GitHub source that a user-started sandbox run of this team uses, so a repository the
    run could not clone is refused here and never silently replaced with another one.
    """
    integration = resolve_team_github_integration(team_id, requester_user_id=user_id)
    if integration is None:
        raise RepositoryCommitError("no_github_integration")
    if not integration.installation_can_access_repository(repository):
        raise RepositoryCommitError("repository_inaccessible")
    sha = integration.get_commit_sha(repository, ref or "HEAD")
    if sha is None:
        raise RepositoryCommitError("invalid_ref")
    return sha


def resolve_team_github_integration_id(team_id: int) -> int | None:
    integration = resolve_team_github_integration(team_id, team_only=True)
    return integration.integration.id if integration is not None else None


__all__ = [
    "REPO_SELECTION_DUMMY_REPOSITORY",
    "RepoSelectionRejectedError",
    "RepoSelectionResult",
    "RepoSelectionUnavailableError",
    "RepoSelectionUsageLimitError",
    "RepositoryCommitError",
    "get_github_token",
    "list_team_connected_repositories",
    "repository_accessible_via_integration",
    "resolve_repository_commit",
    "resolve_team_github_integration",
    "resolve_team_github_integration_id",
    "select_repository",
]
