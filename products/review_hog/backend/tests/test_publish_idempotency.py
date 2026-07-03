from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from github import GithubException
from github.PullRequest import PullRequest

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.persistence import upsert_review_report
from products.review_hog.backend.reviewer.tools.publish_review import (
    PublishOutcome,
    _review_already_posted,
    _review_marker,
)
from products.review_hog.backend.temporal.activities import _publish

# `_publish` now delegates to `publish_persisted_review` in the tool, so the GitHub-post seam and the
# snapshot load are patched there; the installation token is still resolved in the activity wrapper.
_PUBLISH = "products.review_hog.backend.reviewer.tools.publish_review.publish_review"
_SNAPSHOT = "products.review_hog.backend.reviewer.tools.publish_review.load_pr_snapshot"
_TOKEN = "products.review_hog.backend.temporal.activities._installation_token"


class _FakeReview:
    def __init__(self, body: str | None) -> None:
        self.body = body


class _FakePR:
    def __init__(self, reviews: list[_FakeReview], *, boom: bool = False) -> None:
        self._reviews = reviews
        self._boom = boom

    def get_reviews(self) -> list[_FakeReview]:
        if self._boom:
            raise GithubException(500, "boom", None)
        return self._reviews


def _pr(reviews: list[_FakeReview], *, boom: bool = False) -> PullRequest:
    return cast(PullRequest, _FakePR(reviews, boom=boom))


def test_review_already_posted_detects_our_own_markered_review() -> None:
    # Post-then-crash backstop: a review we posted carries this run's marker, so a retry recognizes it
    # and skips. A review without the marker (another turn/author) must not match.
    marker = _review_marker("rep-1", "sha1")
    assert _review_already_posted(_pr([_FakeReview(f"body text\n\n{marker}")]), marker) is True
    assert _review_already_posted(_pr([_FakeReview("an unrelated review"), _FakeReview(None)]), marker) is False
    assert _review_already_posted(_pr([_FakeReview(_review_marker("rep-1", "other-sha"))]), marker) is False


def test_review_already_posted_proceeds_when_readback_fails() -> None:
    # Best-effort: if listing reviews errors we post rather than silently drop the review (the
    # published_head_sha watermark still guards the common retry path).
    assert _review_already_posted(_pr([], boom=True), _review_marker("rep-1", "sha1")) is False


def _pr_metadata(head_sha: str) -> PRMetadata:
    return PRMetadata(
        number=1,
        title="t",
        state="open",
        draft=False,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        author="a",
        base_branch="main",
        head_branch="feat",
        head_sha=head_sha,
        commits=1,
        additions=1,
        deletions=0,
        changed_files=1,
    )


class TestPublishIdempotency(BaseTest):
    def _report(self, *, published_head_sha: str | None = None) -> str:
        report_id = upsert_review_report(
            team_id=self.team.id,
            repository="PostHog/posthog",
            pr_url="https://github.com/PostHog/posthog/pull/1",
            pr_metadata=_pr_metadata("sha1"),
        )
        if published_head_sha is not None:
            ReviewReport.objects.for_team(self.team.id).filter(id=report_id).update(
                published_head_sha=published_head_sha
            )
        return report_id

    @patch(_PUBLISH)
    @patch(_SNAPSHOT, return_value=None)
    @patch(_TOKEN, return_value="tok")
    def test_first_publish_posts_promo_and_records_watermark(self, _token, _snapshot, mock_publish) -> None:
        mock_publish.return_value = PublishOutcome(posted=True)
        report_id = self._report()
        _publish(self.team.id, report_id, "sha1", 1, "PostHog", "posthog", 1, "should_fix")
        assert mock_publish.call_count == 1
        assert mock_publish.call_args.kwargs["post_promo"] is True
        assert ReviewReport.objects.for_team(self.team.id).get(id=report_id).published_head_sha == "sha1"

    @patch(_PUBLISH)
    @patch(_SNAPSHOT, return_value=None)
    @patch(_TOKEN, return_value="tok")
    def test_republish_same_head_is_skipped(self, _token, _snapshot, mock_publish) -> None:
        report_id = self._report(published_head_sha="sha1")
        _publish(self.team.id, report_id, "sha1", 1, "PostHog", "posthog", 1, "should_fix")
        mock_publish.assert_not_called()

    @patch(_PUBLISH)
    @patch(_SNAPSHOT, return_value=None)
    @patch(_TOKEN, return_value="tok")
    def test_new_head_publishes_without_promo(self, _token, _snapshot, mock_publish) -> None:
        mock_publish.return_value = PublishOutcome(posted=True)
        report_id = self._report(published_head_sha="oldsha")
        _publish(self.team.id, report_id, "sha2", 1, "PostHog", "posthog", 1, "should_fix")
        assert mock_publish.call_count == 1
        assert mock_publish.call_args.kwargs["post_promo"] is False
        assert ReviewReport.objects.for_team(self.team.id).get(id=report_id).published_head_sha == "sha2"

    @patch(_PUBLISH)
    @patch(_SNAPSHOT, return_value=None)
    @patch(_TOKEN, return_value="tok")
    def test_noop_publish_does_not_record_watermark(self, _token, _snapshot, mock_publish) -> None:
        # Nothing publishable (validator dropped everything): the head must NOT be watermarked, so a
        # later turn with a valid finding can still publish at the same head.
        mock_publish.return_value = PublishOutcome(posted=False)
        report_id = self._report()
        _publish(self.team.id, report_id, "sha1", 1, "PostHog", "posthog", 1, "should_fix")
        assert mock_publish.call_count == 1
        assert ReviewReport.objects.for_team(self.team.id).get(id=report_id).published_head_sha is None
