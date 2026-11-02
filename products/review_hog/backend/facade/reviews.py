"""Facade for starting a review a PostHog user asked for, and for reading where a pull request's runs stand.

Lives apart from ``github.py`` and ``api.py`` because this path imports the Temporal client, which
the webhook enqueue in ``github.py`` must not load.
"""

from datetime import datetime

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team import Team
from posthog.models.user import User
from posthog.permissions import posthog_feature_flag_enabled

from products.review_hog.backend.facade.contracts import (
    RUN_MODE_FLASH,
    RUN_MODE_REVIEW,
    RUN_MODE_REVIEW_ONLY,
    InvalidPullRequestURLError,
    PRReviewRequestOutcome,
    PRStatus,
)
from products.review_hog.backend.facade.enums import PRReviewRequestStatus
from products.review_hog.backend.pr_status import PRStatusLookup
from products.review_hog.backend.requested_reviews import request_pr_review as _request_pr_review
from products.review_hog.backend.reviewer.tools.github_meta import PRParser
from products.review_hog.backend.temporal.types import TRIGGER_COMMENT, TRIGGER_UI

__all__ = [
    "RUN_MODE_FLASH",
    "RUN_MODE_REVIEW",
    "RUN_MODE_REVIEW_ONLY",
    "PRReviewRequestOutcome",
    "PRReviewRequestStatus",
    "get_pr_review_status",
    "request_pr_review",
    "request_pr_review_by_url",
]

_FEATURE_FLAG = "review-hog"


@frozen
class _PullRequestURL:
    owner: str
    repo: str
    pr_number: int

    @classmethod
    def parse(cls, pr_url: str) -> "_PullRequestURL":
        try:
            pr_info = PRParser().parse_github_pr_url(pr_url)
        except ValueError as e:
            raise InvalidPullRequestURLError(str(e)) from e
        return cls(owner=str(pr_info["owner"]), repo=str(pr_info["repo"]), pr_number=int(pr_info["pr_number"]))


def request_pr_review(
    *, team_id: int, requester_id: int, repository: str, pr_number: int, run_mode: str
) -> PRReviewRequestOutcome:
    """Start the run, with the requester as both the run user and the acting user.

    This is the pull request comment path. The run uses the commenter's settings. The resolution
    stage writes commits only when the pull request owner opted in, the same rule as every trigger.
    Applies the `review-hog` flag, which the review API applies through its permission class.
    The caller has already checked that the requester is a member of the project.
    Raises `GitHubRateLimitError` when GitHub rate-limits the App's token.
    """
    requester = User.objects.get(id=requester_id)
    organization_id = Team.objects.values_list("organization_id", flat=True).get(id=team_id)
    # Access is gated per environment, like the review API's permission class, while review data
    # is shared under the parent project.
    if not posthog_feature_flag_enabled(
        _FEATURE_FLAG, str(requester.distinct_id), organization_id=organization_id, team_id=team_id
    ):
        return PRReviewRequestOutcome(
            status=PRReviewRequestStatus.NOT_ALLOWED, error="PostHog Review isn't enabled for this project."
        )
    owner, _, repo = repository.partition("/")
    return _request_pr_review(
        team_id=resolve_effective_team_id(team_id),
        requester_id=requester_id,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        run_mode=run_mode,
        trigger_source=TRIGGER_COMMENT,
    )


def request_pr_review_by_url(*, team_id: int, requester_id: int, pr_url: str, run_mode: str) -> PRReviewRequestOutcome:
    """Start the run the review API asked for, with the requester as both the run user and the acting user.

    `team_id` is the root project id. The caller applies the `review-hog` flag. Raises
    `InvalidPullRequestURLError` when `pr_url` is not a pull request URL, and `GitHubRateLimitError`
    when GitHub rate-limits the App's token.
    """
    pull_request = _PullRequestURL.parse(pr_url)
    return _request_pr_review(
        team_id=team_id,
        requester_id=requester_id,
        owner=pull_request.owner,
        repo=pull_request.repo,
        pr_number=pull_request.pr_number,
        run_mode=run_mode,
        trigger_source=TRIGGER_UI,
    )


def get_pr_review_status(
    *, team_id: int, pr_url: str, requested_at: datetime | None, run_mode: str, head_sha: str | None
) -> PRStatus:
    """Where the pull request's review runs stand, and how the request at `requested_at` ended.

    `team_id` is the root project id. Raises `InvalidPullRequestURLError` when `pr_url` is not a pull
    request URL.
    """
    pull_request = _PullRequestURL.parse(pr_url)
    return PRStatusLookup(
        team_id, owner=pull_request.owner, repo=pull_request.repo, pr_number=pull_request.pr_number
    ).status(requested_at, run_mode, head_sha)
