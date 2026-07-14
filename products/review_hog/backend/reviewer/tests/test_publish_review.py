from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.egress.github.transport import GitHubRateLimitError

from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding, ValidationVerdict
from products.review_hog.backend.reviewer.constants import published_priorities_for
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority, LineRange
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError
from products.review_hog.backend.reviewer.tools.publish_review import (
    ReviewComment,
    _build_inline_comments,
    _post_github_review,
    publish_review,
)

_REQUEST = "products.review_hog.backend.reviewer.tools.publish_review.github_api_request"
_PAGINATED = "products.review_hog.backend.reviewer.tools.publish_review.github_api_get_paginated"
_REPORT = "products.review_hog.backend.reviewer.tools.publish_review.ReviewReport"
_LOAD_FINDINGS = "products.review_hog.backend.reviewer.tools.publish_review.load_valid_findings"
_POST = "products.review_hog.backend.reviewer.tools.publish_review._post_github_review"

# The default (should_fix) threshold — matches the pre-threshold PUBLISHED_PRIORITIES behavior these
# tests were written against.
_DEFAULT_PUBLISHED = published_priorities_for(IssuePriority.SHOULD_FIX)


def _wire_readbacks(
    mock_paginated: MagicMock,
    reviews: list[dict[str, Any]] | None = None,
    issue_comments: list[dict[str, Any]] | None = None,
) -> None:
    """Route the two idempotency readbacks: prior reviews (marker scan) and issue comments (promo scan)."""

    def paginated(path: str, **kwargs: Any):
        if path.endswith("/reviews"):
            return iter(reviews or [])
        if "/issues/" in path:
            return iter(issue_comments or [])
        raise AssertionError(f"Unexpected paginated path: {path}")

    mock_paginated.side_effect = paginated


def _review_posts(mock_request: MagicMock) -> list[dict[str, Any]]:
    """The JSON payloads of every `POST .../pulls/{n}/reviews` the code issued."""
    return [
        c.kwargs["json"] for c in mock_request.call_args_list if c.args[0] == "POST" and c.args[1].endswith("/reviews")
    ]


def _promo_posts(mock_request: MagicMock) -> list[dict[str, Any]]:
    """The JSON payloads of every `POST .../issues/{n}/comments` the code issued."""
    return [c.kwargs["json"] for c in mock_request.call_args_list if c.args[0] == "POST" and "/issues/" in c.args[1]]


def _commit_probes(mock_request: MagicMock) -> list[str]:
    """The paths of every `GET .../commits/{sha}` pin probe the code issued."""
    return [c.args[1] for c in mock_request.call_args_list if c.args[0] == "GET" and "/commits/" in c.args[1]]


@patch(_PAGINATED)
@patch(_REQUEST)
class TestPostGithubReview:
    def test_uses_passed_token_and_pins_review_to_head_sha(
        self, mock_request: MagicMock, mock_paginated: MagicMock
    ) -> None:
        _wire_readbacks(mock_paginated)
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

        # The installation token (not an env PAT) authenticates every call.
        assert all(c.kwargs["token"] == "install-token" for c in mock_request.call_args_list)
        # The review is pinned to the reviewed commit so a later force-push can't misplace comments.
        assert _commit_probes(mock_request) == ["/repos/o/r/commits/deadbeef"]
        (payload,) = _review_posts(mock_request)
        assert payload["commit_id"] == "deadbeef"
        assert payload["comments"] == comments

    def test_no_head_sha_posts_without_commit_pin(self, mock_request: MagicMock, mock_paginated: MagicMock) -> None:
        _wire_readbacks(mock_paginated)

        _post_github_review(
            "o", "r", 1, "body", [], token="t", head_sha="", post_promo=True, marker="m", promo_marker="pm"
        )

        assert _commit_probes(mock_request) == []
        (payload,) = _review_posts(mock_request)
        assert "commit_id" not in payload

    def test_unresolvable_head_sha_degrades_to_unpinned_instead_of_failing(
        self, mock_request: MagicMock, mock_paginated: MagicMock
    ) -> None:
        _wire_readbacks(mock_paginated)

        def request(method: str, path: str, **kwargs: Any) -> MagicMock:
            if "/commits/" in path:
                raise GitHubAPIError("GitHub API GET returned 422: No commit found", status=422)
            return MagicMock()

        mock_request.side_effect = request

        # Must not raise — a stale/unreachable reviewed commit should still post the review unpinned.
        _post_github_review(
            "o", "r", 1, "body", [], token="t", head_sha="deadbeef", post_promo=False, marker="m", promo_marker="pm"
        )

        (payload,) = _review_posts(mock_request)
        assert "commit_id" not in payload

    def test_promo_comment_only_posted_when_requested(self, mock_request: MagicMock, mock_paginated: MagicMock) -> None:
        _wire_readbacks(mock_paginated)

        _post_github_review(
            "o", "r", 1, "body", [], token="t", head_sha="s", post_promo=False, marker="m", promo_marker="pm"
        )
        assert _promo_posts(mock_request) == []

        mock_request.reset_mock()
        _post_github_review(
            "o", "r", 1, "body", [], token="t", head_sha="s", post_promo=True, marker="m", promo_marker="pm"
        )
        (promo,) = _promo_posts(mock_request)
        # The idempotency marker rides inside the posted comment body.
        assert "pm" in promo["body"]

    @parameterized.expand(
        [
            ("server_error", GitHubAPIError("GitHub API POST returned 500: boom", status=500)),
            ("rate_limited", GitHubRateLimitError("rate limited", retry_after=60)),
        ]
    )
    def test_transient_comment_post_failure_raises_instead_of_dropping_comments(
        self, mock_request: MagicMock, mock_paginated: MagicMock, _name: str, error: Exception
    ) -> None:
        # A 5xx / rate limit says nothing about the comment payload — falling back to a body-only post
        # here would permanently discard every inline comment; raising lets the activity retry keep them.
        _wire_readbacks(mock_paginated)
        comments: list[ReviewComment] = [{"path": "a.py", "body": "x", "side": "RIGHT", "line": 1}]

        def request(method: str, path: str, **kwargs: Any) -> MagicMock:
            if method == "POST" and path.endswith("/reviews"):
                raise error
            return MagicMock()

        mock_request.side_effect = request

        with pytest.raises(type(error)):
            _post_github_review(
                "o", "r", 1, "body", comments, token="t", head_sha="", post_promo=False, marker="m", promo_marker="pm"
            )

        (payload,) = _review_posts(mock_request)  # exactly one attempt — no body-only fallback post
        assert payload["comments"] == comments

    def test_comment_payload_rejection_falls_back_to_body_only(
        self, mock_request: MagicMock, mock_paginated: MagicMock
    ) -> None:
        # 422 = GitHub rejected the comment payload itself; a retry would hit the same wall, so the
        # review must still land as body-only rather than failing the publish forever.
        _wire_readbacks(mock_paginated)
        comments: list[ReviewComment] = [{"path": "a.py", "body": "x", "side": "RIGHT", "line": 1}]

        def request(method: str, path: str, **kwargs: Any) -> MagicMock:
            if method == "POST" and path.endswith("/reviews") and "comments" in (kwargs.get("json") or {}):
                raise GitHubAPIError("GitHub API POST returned 422: Unprocessable Entity", status=422)
            return MagicMock()

        mock_request.side_effect = request

        _post_github_review(
            "o", "r", 1, "body", comments, token="t", head_sha="", post_promo=False, marker="m", promo_marker="pm"
        )

        first, second = _review_posts(mock_request)
        assert first["comments"] == comments
        assert "comments" not in second

    def test_skips_when_a_review_with_our_marker_is_already_present(
        self, mock_request: MagicMock, mock_paginated: MagicMock
    ) -> None:
        # Post-then-crash idempotency: a review already carrying this run's marker means we posted but
        # didn't record the watermark, so the retry must post neither a second review nor the promo.
        _wire_readbacks(mock_paginated, reviews=[{"body": "an earlier review\n\nmarker-xyz"}])

        _post_github_review(
            "o", "r", 1, "body", [], token="t", head_sha="s", post_promo=True, marker="marker-xyz", promo_marker="pm"
        )

        mock_request.assert_not_called()


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
