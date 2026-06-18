"""
Facade re-exports for repository selection.

The repo-selection agent picks a GitHub repository for a task given free-text context. Its
result type and errors are framework-free; other products call ``select_repository`` and
handle the typed outcomes.
"""

from products.tasks.backend.logic.repo_selection import (
    REPO_SELECTION_DUMMY_REPOSITORY,
    RepoSelectionRejectedError,
    RepoSelectionResult,
    RepoSelectionUnavailableError,
    resolve_team_github_integration,
    select_repository,
)

__all__ = [
    "REPO_SELECTION_DUMMY_REPOSITORY",
    "RepoSelectionRejectedError",
    "RepoSelectionResult",
    "RepoSelectionUnavailableError",
    "resolve_team_github_integration",
    "select_repository",
]
