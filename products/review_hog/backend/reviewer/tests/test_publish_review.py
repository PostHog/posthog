from unittest.mock import MagicMock, patch

from github import GithubException
from github.PullRequest import ReviewComment
from parameterized import parameterized

from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding, ValidationVerdict
from products.review_hog.backend.reviewer.constants import published_priorities_for
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority, LineRange
from products.review_hog.backend.reviewer.tools.publish_review import (
    _build_inline_comments,
    _post_github_review,
    publish_review,
)

_GITHUB = "products.review_hog.backend.reviewer.tools.publish_review.Github"
_REPORT = "products.review_hog.backend.reviewer.tools.publish_review.ReviewReport"
_LOAD_FINDINGS = "products.review_hog.backend.reviewer.tools.publish_review.load_valid_findings"
_POST = "products.review_hog.backend.reviewer.tools.publish_review._post_github_review"

# The default (should_fix) threshold — matches the pre-threshold PUBLISHED_PRIORITIES behavior these
# tests were written against.
_DEFAULT_PUBLISHED = published_priorities_for(IssuePriority.SHOULD_FIX)


class TestPostGithubReview:
    def _wire_github(self, mock_github_class: MagicMock) -> tuple[MagicMock, MagicMock, MagicMock]:
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_commit = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        mock_repo.get_commit.return_value = mock_commit
        mock_pr.get_reviews.return_value = []  # no prior review carries our marker → post proceeds
        mock_pr.get_issue_comments.return_value = []  # no prior promo comment → promo may post
        mock_github_class.return_value.get_repo.return_value = mock_repo
        return mock_repo, mock_pr, mock_commit

    @patch(_GITHUB)
    def test_uses_passed_token_and_pins_review_to_head_sha(self, mock_github_class: MagicMock) -> None:
        _, mock_pr, mock_commit = self._wire_github(mock_github_class)
        comments: list[ReviewComment] = [{"path": "a.py", "body": "x", "side": "RIGHT", "line": 1}]

        _post_github_review(
            "o",
            "r",
            1,
            "body",
            comments,
            token="install-token",
            head_sha="deadbeef",
            post_promo=True,
            marker="m",
            promo_marker="pm",
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

        _post_github_review(
            "o", "r", 1, "body", [], token="t", head_sha="", post_promo=True, marker="m", promo_marker="pm"
        )

        mock_repo.get_commit.assert_not_called()
        assert "commit" not in mock_pr.create_review.call_args.kwargs

    @patch(_GITHUB)
    def test_unresolvable_head_sha_degrades_to_unpinned_instead_of_failing(self, mock_github_class: MagicMock) -> None:
        mock_repo, mock_pr, _ = self._wire_github(mock_github_class)
        mock_repo.get_commit.side_effect = GithubException(422, {"message": "No commit found"})

        # Must not raise — a stale/unreachable reviewed commit should still post the review unpinned.
        _post_github_review(
            "o", "r", 1, "body", [], token="t", head_sha="deadbeef", post_promo=False, marker="m", promo_marker="pm"
        )

        assert "commit" not in mock_pr.create_review.call_args.kwargs
        mock_pr.create_review.assert_called_once()

    @patch(_GITHUB)
    def test_promo_comment_only_posted_when_requested(self, mock_github_class: MagicMock) -> None:
        _, mock_pr, _ = self._wire_github(mock_github_class)

        _post_github_review(
            "o", "r", 1, "body", [], token="t", head_sha="s", post_promo=False, marker="m", promo_marker="pm"
        )
        mock_pr.create_issue_comment.assert_not_called()

        _post_github_review(
            "o", "r", 1, "body", [], token="t", head_sha="s", post_promo=True, marker="m", promo_marker="pm"
        )
        mock_pr.create_issue_comment.assert_called_once()
        # The idempotency marker rides inside the posted comment body.
        assert "pm" in mock_pr.create_issue_comment.call_args.args[0]

    @patch(_GITHUB)
    def test_skips_when_a_review_with_our_marker_is_already_present(self, mock_github_class: MagicMock) -> None:
        # Post-then-crash idempotency: a review already carrying this run's marker means we posted but
        # didn't record the watermark, so the retry must post neither a second review nor the promo.
        _, mock_pr, _ = self._wire_github(mock_github_class)
        existing = MagicMock()
        existing.body = "an earlier review\n\nmarker-xyz"
        mock_pr.get_reviews.return_value = [existing]

        _post_github_review(
            "o", "r", 1, "body", [], token="t", head_sha="s", post_promo=True, marker="marker-xyz", promo_marker="pm"
        )

        mock_pr.create_review.assert_not_called()
        mock_pr.create_issue_comment.assert_not_called()


_ISSUE_KEY = "r1:src/auth.py:240:Logic & Correctness:1-1-1"


def _finding(priority: IssuePriority = IssuePriority.SHOULD_FIX) -> ReviewIssueFinding:
    # An off-diff finding (line 240) — its diff position can't resolve, so it never gets an inline comment.
    return ReviewIssueFinding(
        issue_key=_ISSUE_KEY,
        run_index=1,
        title="Off-diff finding",
        file="src/auth.py",
        lines=[LineRange(start=240, end=240)],
        body="problem",
        suggestion="fix",
        priority=priority,
    )


def _verdict(adjusted_priority: IssuePriority | None = None) -> ValidationVerdict:
    return ValidationVerdict(
        issue_key=_ISSUE_KEY,
        is_valid=True,
        argumentation="reason",
        category="bug",
        adjusted_priority=adjusted_priority,
    )


class TestPublishReviewGate:
    def _wire_report(self, mock_report_cls: MagicMock) -> None:
        mock_report = MagicMock()
        mock_report.report_markdown = "# ReviewHog Report"
        mock_report_cls.objects.for_team.return_value.get.return_value = mock_report

    @patch(_POST)
    @patch(_LOAD_FINDINGS)
    @patch(_REPORT)
    def test_posts_body_when_all_publishable_findings_are_off_diff(
        self, mock_report_cls: MagicMock, mock_load: MagicMock, mock_post: MagicMock
    ) -> None:
        # A valid should_fix finding on an off-diff line resolves zero inline comments — but the review
        # (its body carries it in the "Other findings" section) must still post, not be silently dropped.
        self._wire_report(mock_report_cls)
        mock_load.return_value = [(_finding(), _verdict())]

        outcome = publish_review(
            owner="o",
            repo="r",
            pr_number=1,
            team_id=1,
            report_id="rep",
            run_index=1,
            pr_files=[],
            token="t",
            head_sha="sha",
            post_promo=False,
            published_priorities=_DEFAULT_PUBLISHED,
        )

        assert outcome.posted is True
        mock_post.assert_called_once()
        assert mock_post.call_args.args[4] == []  # body-only post: no inline comments resolved

    @patch(_POST)
    @patch(_LOAD_FINDINGS)
    @patch(_REPORT)
    def test_skips_when_only_consider_findings(
        self, mock_report_cls: MagicMock, mock_load: MagicMock, mock_post: MagicMock
    ) -> None:
        # Below the default should_fix threshold: a run whose only valid finding is `consider` has
        # nothing publishable, so it posts nothing (guards the off-diff fix against over-surfacing).
        self._wire_report(mock_report_cls)
        mock_load.return_value = [(_finding(priority=IssuePriority.CONSIDER), _verdict())]

        outcome = publish_review(
            owner="o",
            repo="r",
            pr_number=1,
            team_id=1,
            report_id="rep",
            run_index=1,
            pr_files=[],
            token="t",
            head_sha="sha",
            post_promo=False,
            published_priorities=_DEFAULT_PUBLISHED,
        )

        assert outcome.posted is False
        mock_post.assert_not_called()

    @parameterized.expand(
        [
            # The validator wins: an upgraded consider crosses the publish bar; a downgraded should_fix
            # drops below it — gating reads the effective priority, not the reviewer's frozen one.
            ("upgrade_consider_publishes", IssuePriority.CONSIDER, IssuePriority.SHOULD_FIX, True),
            ("downgrade_should_fix_suppresses", IssuePriority.SHOULD_FIX, IssuePriority.CONSIDER, False),
        ]
    )
    @patch(_POST)
    @patch(_LOAD_FINDINGS)
    @patch(_REPORT)
    def test_validator_override_gates_publish(
        self,
        _name: str,
        base: IssuePriority,
        adjusted: IssuePriority,
        expected_posted: bool,
        mock_report_cls: MagicMock,
        mock_load: MagicMock,
        mock_post: MagicMock,
    ) -> None:
        self._wire_report(mock_report_cls)
        mock_load.return_value = [(_finding(priority=base), _verdict(adjusted_priority=adjusted))]

        outcome = publish_review(
            owner="o",
            repo="r",
            pr_number=1,
            team_id=1,
            report_id="rep",
            run_index=1,
            pr_files=[],
            token="t",
            head_sha="sha",
            post_promo=False,
            published_priorities=_DEFAULT_PUBLISHED,
        )

        assert outcome.posted is expected_posted
        assert mock_post.called is expected_posted

    @parameterized.expand(
        [
            # On-diff finding (line 240 IS in the diff), so position always resolves — inclusion is then
            # decided ONLY by the effective priority. Guards the inline filter against regressing to the
            # raw priority (the publish gate test can't: it uses an off-diff finding that yields no comment).
            ("downgrade_drops_the_inline_comment", IssuePriority.SHOULD_FIX, IssuePriority.CONSIDER, 0),
            ("upgrade_adds_the_inline_comment", IssuePriority.CONSIDER, IssuePriority.SHOULD_FIX, 1),
        ]
    )
    def test_build_inline_comments_honors_effective_priority(
        self, _name: str, base: IssuePriority, adjusted: IssuePriority, expected_count: int
    ) -> None:
        diff_lines = {"src/auth.py": {240}}
        comments = _build_inline_comments(
            [(_finding(priority=base), _verdict(adjusted_priority=adjusted))], diff_lines, _DEFAULT_PUBLISHED
        )

        assert len(comments) == expected_count
        if expected_count:
            assert "should_fix" in comments[0]["body"]  # the emitted comment displays the effective priority
