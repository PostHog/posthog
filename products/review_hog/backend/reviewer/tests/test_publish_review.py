from unittest.mock import MagicMock, patch

from github import GithubException

from products.review_hog.backend.reviewer.tools.publish_review import _post_github_review

_GITHUB = "products.review_hog.backend.reviewer.tools.publish_review.Github"


class TestPostGithubReview:
    def _wire_github(self, mock_github_class: MagicMock) -> tuple[MagicMock, MagicMock, MagicMock]:
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_commit = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        mock_repo.get_commit.return_value = mock_commit
        mock_pr.get_reviews.return_value = []  # no prior review carries our marker → post proceeds
        mock_github_class.return_value.get_repo.return_value = mock_repo
        return mock_repo, mock_pr, mock_commit

    @patch(_GITHUB)
    def test_uses_passed_token_and_pins_review_to_head_sha(self, mock_github_class: MagicMock) -> None:
        _, mock_pr, mock_commit = self._wire_github(mock_github_class)
        comments = [{"path": "a.py", "body": "x", "side": "RIGHT", "line": 1}]

        _post_github_review(
            "o", "r", 1, "body", comments, token="install-token", head_sha="deadbeef", post_promo=True, marker="m"
        )

        # The installation token (not an env PAT) authenticates the client.
        mock_github_class.assert_called_once_with("install-token")
        # The review is pinned to the reviewed commit so a later force-push can't misplace comments.
        kwargs = mock_pr.create_review.call_args.kwargs
        assert kwargs["commit"] is mock_commit
        assert kwargs["comments"] == comments

    @patch(_GITHUB)
    def test_no_head_sha_posts_without_commit_pin(self, mock_github_class: MagicMock) -> None:
        mock_repo, mock_pr, _ = self._wire_github(mock_github_class)

        _post_github_review("o", "r", 1, "body", [], token="t", head_sha="", post_promo=True, marker="m")

        mock_repo.get_commit.assert_not_called()
        assert "commit" not in mock_pr.create_review.call_args.kwargs

    @patch(_GITHUB)
    def test_unresolvable_head_sha_degrades_to_unpinned_instead_of_failing(self, mock_github_class: MagicMock) -> None:
        mock_repo, mock_pr, _ = self._wire_github(mock_github_class)
        mock_repo.get_commit.side_effect = GithubException(422, {"message": "No commit found"})

        # Must not raise — a stale/unreachable reviewed commit should still post the review unpinned.
        _post_github_review("o", "r", 1, "body", [], token="t", head_sha="deadbeef", post_promo=False, marker="m")

        assert "commit" not in mock_pr.create_review.call_args.kwargs
        mock_pr.create_review.assert_called_once()

    @patch(_GITHUB)
    def test_promo_comment_only_posted_when_requested(self, mock_github_class: MagicMock) -> None:
        _, mock_pr, _ = self._wire_github(mock_github_class)

        _post_github_review("o", "r", 1, "body", [], token="t", head_sha="s", post_promo=False, marker="m")
        mock_pr.create_issue_comment.assert_not_called()

        _post_github_review("o", "r", 1, "body", [], token="t", head_sha="s", post_promo=True, marker="m")
        mock_pr.create_issue_comment.assert_called_once()

    @patch(_GITHUB)
    def test_skips_when_a_review_with_our_marker_is_already_present(self, mock_github_class: MagicMock) -> None:
        # Post-then-crash idempotency: a review already carrying this run's marker means we posted but
        # didn't record the watermark, so the retry must post neither a second review nor the promo.
        _, mock_pr, _ = self._wire_github(mock_github_class)
        existing = MagicMock()
        existing.body = "an earlier review\n\nmarker-xyz"
        mock_pr.get_reviews.return_value = [existing]

        _post_github_review("o", "r", 1, "body", [], token="t", head_sha="s", post_promo=True, marker="marker-xyz")

        mock_pr.create_review.assert_not_called()
        mock_pr.create_issue_comment.assert_not_called()
