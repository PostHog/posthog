from collections.abc import Callable, Iterator
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.persistence import upsert_review_report
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError
from products.review_hog.backend.reviewer.tools.publish_review import (
    PublishOutcome,
    _promo_already_posted,
    _promo_marker,
    _review_already_posted,
    _review_marker,
)
from products.review_hog.backend.temporal.activities import _publish

# `_publish` now delegates to `publish_persisted_review` in the tool, so the GitHub-post seam and the
# snapshot load are patched there; the installation auth is still resolved in the activity wrapper.
_PUBLISH = "products.review_hog.backend.reviewer.tools.publish_review.publish_review"
_SNAPSHOT = "products.review_hog.backend.reviewer.tools.publish_review.load_pr_snapshot"
_AUTH = "products.review_hog.backend.temporal.activities._installation_auth"
_PAGINATED = "products.review_hog.backend.reviewer.tools.publish_review.github_api_get_paginated"


def _paginated(items: list[dict[str, Any]], *, boom: bool = False) -> Callable[..., Iterator[dict[str, Any]]]:
    """A github_api_get_paginated stand-in yielding `items` (or failing the readback with `boom`)."""

    def fake(path: str, **kwargs: Any) -> Iterator[dict[str, Any]]:
        if boom:
            raise GitHubAPIError("readback failed", status=500)
        return iter(items)

    return fake


def _review_posted(marker: str, reviews: list[dict[str, Any]], *, boom: bool = False) -> bool:
    with patch(_PAGINATED, side_effect=_paginated(reviews, boom=boom)):
        return _review_already_posted("o", "r", 1, marker, token="t", installation_id=None)


def _promo_posted(marker: str, comments: list[dict[str, Any]], *, boom: bool = False) -> bool:
    with patch(_PAGINATED, side_effect=_paginated(comments, boom=boom)):
        return _promo_already_posted("o", "r", 1, marker, token="t", installation_id=None)


def test_review_already_posted_detects_our_own_markered_review() -> None:
    # Post-then-crash backstop: a review we posted carries this run's marker, so a retry recognizes it
    # and skips. A review without the marker (another turn/author) must not match.
    marker = _review_marker("rep-1", "sha1")
    assert _review_posted(marker, [{"body": f"body text\n\n{marker}"}]) is True
    assert _review_posted(marker, [{"body": "an unrelated review"}, {"body": None}]) is False
    assert _review_posted(marker, [{"body": _review_marker("rep-1", "other-sha")}]) is False


def test_review_already_posted_proceeds_when_readback_fails() -> None:
    # Best-effort: if listing reviews errors we post rather than silently drop the review (the
    # published_head_sha watermark still guards the common retry path).
    assert _review_posted(_review_marker("rep-1", "sha1"), [], boom=True) is False


def test_promo_already_posted_detects_the_markered_comment() -> None:
    # The promo posts before the review, so a retry after a transient review failure re-enters
    # with published_head_sha still unset — the marker is what stops a second promo comment.
    marker = _promo_marker("rep-1")
    assert _promo_posted(marker, [{"body": f"promo text\n\n{marker}"}]) is True
    assert _promo_posted(marker, [{"body": "unrelated comment"}, {"body": None}]) is False


def test_promo_already_posted_skips_when_readback_fails() -> None:
    # Inverted stakes vs the review readback: a duplicate promo is spam while a missing one is
    # harmless, so an unreadable comment list counts as already posted.
    assert _promo_posted(_promo_marker("rep-1"), [], boom=True) is True


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
    @patch(_AUTH, return_value=("tok", "9876543"))
    def test_first_publish_posts_promo_and_records_watermark(self, _auth, _snapshot, mock_publish) -> None:
        mock_publish.return_value = PublishOutcome(posted=True)
        report_id = self._report()
        _publish(self.team.id, report_id, "sha1", 1, "PostHog", "posthog", 1, "should_fix")
        assert mock_publish.call_count == 1
        assert mock_publish.call_args.kwargs["post_promo"] is True
        # The resolved installation id must reach the GitHub calls — dropping it silently turns the
        # publish identity-blind (no egress budget accounting).
        assert mock_publish.call_args.kwargs["installation_id"] == "9876543"
        assert ReviewReport.objects.for_team(self.team.id).get(id=report_id).published_head_sha == "sha1"

    @patch(_PUBLISH)
    @patch(_SNAPSHOT, return_value=None)
    @patch(_AUTH, return_value=("tok", None))
    def test_republish_same_head_is_skipped(self, _auth, _snapshot, mock_publish) -> None:
        report_id = self._report(published_head_sha="sha1")
        _publish(self.team.id, report_id, "sha1", 1, "PostHog", "posthog", 1, "should_fix")
        mock_publish.assert_not_called()

    @patch(_PUBLISH)
    @patch(_SNAPSHOT, return_value=None)
    @patch(_AUTH, return_value=("tok", None))
    def test_new_head_publishes_without_promo(self, _auth, _snapshot, mock_publish) -> None:
        mock_publish.return_value = PublishOutcome(posted=True)
        report_id = self._report(published_head_sha="oldsha")
        _publish(self.team.id, report_id, "sha2", 1, "PostHog", "posthog", 1, "should_fix")
        assert mock_publish.call_count == 1
        assert mock_publish.call_args.kwargs["post_promo"] is False
        assert ReviewReport.objects.for_team(self.team.id).get(id=report_id).published_head_sha == "sha2"

    @patch(_PUBLISH)
    @patch(_SNAPSHOT, return_value=None)
    @patch(_AUTH, return_value=("tok", None))
    def test_noop_publish_does_not_record_watermark(self, _auth, _snapshot, mock_publish) -> None:
        # Nothing publishable (validator dropped everything): the head must NOT be watermarked, so a
        # later turn with a valid finding can still publish at the same head.
        mock_publish.return_value = PublishOutcome(posted=False)
        report_id = self._report()
        _publish(self.team.id, report_id, "sha1", 1, "PostHog", "posthog", 1, "should_fix")
        assert mock_publish.call_count == 1
        assert ReviewReport.objects.for_team(self.team.id).get(id=report_id).published_head_sha is None
