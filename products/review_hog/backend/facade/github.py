from products.review_hog.backend.ownership import RepositoryOwnership, RepositoryRef
from products.review_hog.backend.pull_request_events import accept_pull_request_event


def owning_team_id(installation_id: str, repository: str, github_repo_id: int | None = None) -> int | None:
    """The project that reviews `repository` (`owner/name`) for this installation, or None when none does."""
    owner = RepositoryOwnership.find(
        RepositoryRef(installation_id=installation_id, github_repo_id=github_repo_id, full_name=repository)
    )
    return owner.team_id if owner is not None else None


__all__ = ["accept_pull_request_event", "owning_team_id"]
