"""Resolve a repository ref to one commit with the GitHub source that the team's sandbox runs use."""

from typing import Literal

from products.tasks.backend.logic.repo_selection import resolve_team_github_integration


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
