"""Facade for reading where PostHog Review's review of one pull request head stands.

Any product may read it, except one that review_hog depends on: stamphog gets the same answer
through the provider that `receivers.connect()` registers, because importing review_hog there would
be a dependency cycle. Lives apart from `reviews.py` and `github.py` because the lookup imports the
Temporal client.
"""

from products.review_hog.backend.facade.review_status_types import HeadReviewState, HeadReviewStatus
from products.review_hog.backend.head_review_status import HeadReviewStatusLookup
from products.review_hog.backend.ownership import RepositoryOwnership

__all__ = ["HeadReviewState", "HeadReviewStatus", "review_status_for_head"]


def review_status_for_head(repository: str, pr_number: int, head_sha: str) -> HeadReviewStatus | None:
    """The status of the review of exactly `head_sha`, or None when none is known.

    None also when no project reviews the repository. Raises when Temporal does not answer the
    queue query, so a caller cannot read an outage as "nothing pending".
    """
    owner = RepositoryOwnership.find_by_name(repository)
    if owner is None:
        return None
    return HeadReviewStatusLookup(owner.team_id, repository, pr_number, head_sha).status()
