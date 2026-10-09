"""Facade for starting a review a PostHog user asked for, from outside the review API.

Lives apart from ``github.py`` because this path imports the Temporal client, which the webhook
enqueue in ``github.py`` must not load.
"""

from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team import Team
from posthog.models.user import User
from posthog.permissions import posthog_feature_flag_enabled

from products.review_hog.backend.requested_reviews import (
    RUN_MODE_FLASH,
    RUN_MODE_REVIEW,
    PRReviewRequestOutcome,
    PRReviewRequestStatus,
    request_pr_review as _request_pr_review,
)
from products.review_hog.backend.temporal.types import TRIGGER_COMMENT

__all__ = [
    "RUN_MODE_FLASH",
    "RUN_MODE_REVIEW",
    "PRReviewRequestOutcome",
    "PRReviewRequestStatus",
    "request_pr_review",
]

_FEATURE_FLAG = "review-hog"


def request_pr_review(
    *, team_id: int, requester_id: int, repository: str, pr_number: int, run_mode: str
) -> PRReviewRequestOutcome:
    """Start the run, with the requester as both the run user and the acting user.

    This is the pull request comment path. The run uses the commenter's settings, but the resolution
    stage writes commits to the pull request's branch. Until the pull request owner's own opt-in
    decides that, a comment must not write to anyone's branch, so resolution stays off.
    Applies the `review-hog` flag, which the review API applies through its permission class.
    The caller has already checked that the requester is a member of the project.
    Raises `GitHubRateLimitError` when GitHub rate-limits the App's token.
    """
    effective_team_id = resolve_effective_team_id(team_id)
    requester = User.objects.get(id=requester_id)
    organization_id = Team.objects.values_list("organization_id", flat=True).get(id=effective_team_id)
    if not posthog_feature_flag_enabled(
        _FEATURE_FLAG, str(requester.distinct_id), organization_id=organization_id, team_id=effective_team_id
    ):
        return PRReviewRequestOutcome(
            status=PRReviewRequestStatus.NOT_ALLOWED, error="PostHog Review isn't enabled for this project."
        )
    owner, _, repo = repository.partition("/")
    return _request_pr_review(
        team_id=effective_team_id,
        requester_id=requester_id,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        run_mode=run_mode,
        trigger_source=TRIGGER_COMMENT,
        resolve_comments=False,
    )
