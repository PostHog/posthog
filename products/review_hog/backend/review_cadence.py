"""When a repository's pull requests get automatic reviews: the four cadences of two repository switches.

| `review_drafts` | `review_pushes` | Draft opens | Marked ready | Pushes after ready |
| --------------- | --------------- | ----------- | ------------ | ------------------ |
| off             | off             | -           | review       | -                  |
| off             | on              | -           | review       | push gate          |
| on              | off             | review      | review       | -                  |
| on              | on              | review      | review       | push gate          |

A push to a draft never gets an automatic review. A pull request that opens ready for review starts
at "Marked ready". The push gate judges every automatic review after the first one, the review at
ready included.

The webhook dispatch, the push gate and the note a review ends with all ask `ReviewCadence`, so they
cannot disagree about a cadence.
"""

from posthog.dataclasses import frozen

from products.review_hog.backend.models import ReviewRepository
from products.review_hog.backend.ownership import RepositoryOwnership

READY_FOR_REVIEW_ACTION = "ready_for_review"


@frozen
class ReviewCadence:
    review_drafts: bool
    review_pushes: bool

    @classmethod
    def of(cls, row: ReviewRepository | None) -> "ReviewCadence":
        """A repository without a row has both switches off."""
        if row is None:
            return cls(review_drafts=False, review_pushes=False)
        return cls(review_drafts=row.review_drafts, review_pushes=row.review_pushes)

    @classmethod
    def load(cls, team_id: int, repository: str) -> "ReviewCadence":
        """The cadence of a repository known only by name. A repository another project owns has both switches off."""
        owner = RepositoryOwnership.find_by_name(repository)
        if owner is None or owner.team_id != team_id:
            return cls.of(None)
        return cls.of(owner.row)

    def reviews_opening_draft(self, *, author_allows: bool) -> bool:
        """Whether a draft gets its first automatic review when it opens. An author can turn this off for their own drafts."""
        return self.review_drafts and author_allows

    def dispatches_follow_up(self, action: str | None) -> bool:
        """Whether a webhook event after the first automatic review starts a turn for the push gate to judge.

        A ready event starts one in every cadence: the gate lets it run only after a draft review, and a
        repository can turn draft reviews off between the draft review and the ready event.
        """
        return self.review_pushes or action == READY_FOR_REVIEW_ACTION

    def allows_follow_up(self, *, reviewed_draft: bool | None, draft: bool | None) -> bool:
        """Whether the push gate lets an automatic turn after the first one run.

        Without push reviews, the only such turn is the review at ready of a pull request whose last automatic
        review saw a draft. `reviewed_draft` is the draft state that review saw, None when unknown. A current
        state that is unknown counts as ready, because a failed read reviews the push.
        """
        if self.review_pushes:
            return True
        return reviewed_draft is True and draft is not True

    def ends_after_ready_review(self) -> bool:
        """Whether the review at ready is the last automatic review, so the review says so."""
        return not self.review_pushes
