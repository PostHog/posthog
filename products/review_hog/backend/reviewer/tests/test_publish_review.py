from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.egress.github.transport import GitHubRateLimitError

from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding, ValidationVerdict
from products.review_hog.backend.reviewer.constants import published_priorities_for
from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRFileUpdate
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority, LineRange
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError
from products.review_hog.backend.reviewer.tools.github_threads import REVIEW_HOG_FINDING_MARKER
from products.review_hog.backend.reviewer.tools.publish_review import (
    FALLBACK_BODY_MAX_CHARS,
    ReviewComment,
    _build_inline_comments,
    _format_issue_comment,
    _post_github_review,
    publish_review,
)

_REQUEST = "products.review_hog.backend.reviewer.tools.publish_review.github_api_request"
_PAGINATED = "products.review_hog.backend.reviewer.tools.publish_review.github_api_get_paginated"
_REPORT = "products.review_hog.backend.reviewer.tools.publish_review.ReviewReport"
_LOAD_FINDINGS = "products.review_hog.backend.reviewer.tools.publish_review.load_valid_findings"
_POST = "products.review_hog.backend.reviewer.tools.publish_review._post_github_review"

# The should_fix threshold: publishes should_fix and must_fix, drops consider. These tests use it to
# exercise the publish gate, not the default (consider), which publishes everything.
_SHOULD_FIX_PUBLISHED = published_priorities_for(IssuePriority.SHOULD_FIX)


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

    def test_credential_shapes_are_scrubbed_before_posting(
        self, mock_request: MagicMock, mock_paginated: MagicMock
    ) -> None:
        _wire_readbacks(mock_paginated)
        comments: list[ReviewComment] = [
            {"path": "a.py", "body": "ran with GH_TOKEN=ghs_abcdefghijklmnopqrstuvwxyz0123", "side": "RIGHT", "line": 1}
        ]

        _post_github_review(
            "o",
            "r",
            1,
            "key phx_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789 seen",
            comments,
            token="install-token",
            head_sha="",
            post_promo=False,
            marker="m",
            promo_marker="pm",
        )

        (payload,) = _review_posts(mock_request)
        assert payload["body"] == "key [redacted] seen"
        assert payload["comments"][0]["body"] == "ran with GH_TOKEN=[redacted]"

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
        comments: list[ReviewComment] = [
            {
                "path": "a.py",
                "body": f"### Token leaks into logs\n\nThe token is logged.\n\n{REVIEW_HOG_FINDING_MARKER}",
                "side": "RIGHT",
                "line": 1,
            }
        ]

        def request(method: str, path: str, **kwargs: Any) -> MagicMock:
            if method == "POST" and path.endswith("/reviews") and "comments" in (kwargs.get("json") or {}):
                raise GitHubAPIError("GitHub API POST returned 422: Unprocessable Entity", status=422)
            return MagicMock()

        mock_request.side_effect = request

        _post_github_review(
            "o",
            "r",
            1,
            "body\n\nm",
            comments,
            token="t",
            head_sha="",
            post_promo=False,
            marker="m",
            promo_marker="pm",
            inline_body="m",
        )

        first, second = _review_posts(mock_request)
        assert first["comments"] == comments
        assert first["body"] == "m"
        assert "comments" not in second
        # The inline-only findings must survive in the fallback body, or the review posts a bare tally.
        assert second["body"].startswith("body\n\nm")
        assert "### Token leaks into logs" in second["body"]
        assert "The token is logged." in second["body"]
        assert REVIEW_HOG_FINDING_MARKER not in second["body"]

    def _fallback_body(self, mock_request: MagicMock, mock_paginated: MagicMock, comments: list[ReviewComment]) -> str:
        _wire_readbacks(mock_paginated)

        def request(method: str, path: str, **kwargs: Any) -> MagicMock:
            if method == "POST" and path.endswith("/reviews") and "comments" in (kwargs.get("json") or {}):
                raise GitHubAPIError("GitHub API POST returned 422: Unprocessable Entity", status=422)
            return MagicMock()

        mock_request.side_effect = request
        _post_github_review(
            "o",
            "r",
            1,
            "body\n\nm",
            comments,
            token="t",
            head_sha="",
            post_promo=False,
            marker="m",
            promo_marker="pm",
            inline_body="m",
        )
        _first, second = _review_posts(mock_request)
        return second["body"]

    def test_fallback_renders_a_path_with_backticks_inside_a_longer_fence(
        self, mock_request: MagicMock, mock_paginated: MagicMock
    ) -> None:
        comments: list[ReviewComment] = [
            {"path": "a`` **x**.py", "body": "finding", "side": "RIGHT", "line": 3},
            {"path": "`edge`", "body": "finding", "side": "RIGHT", "line": 4},
        ]

        body = self._fallback_body(mock_request, mock_paginated, comments)

        assert "```a`` **x**.py:3```" in body
        assert "`` `edge`:4 ``" in body

    def test_fallback_body_stays_under_the_limit_and_reports_omitted_findings(
        self, mock_request: MagicMock, mock_paginated: MagicMock
    ) -> None:
        comments: list[ReviewComment] = [
            {"path": f"f{i}.py", "body": "x" * 10_000, "side": "RIGHT", "line": i} for i in range(10)
        ]

        body = self._fallback_body(mock_request, mock_paginated, comments)

        assert len(body) <= FALLBACK_BODY_MAX_CHARS
        assert "`f0.py:0`" in body
        assert "`f9.py:9`" not in body
        assert "5 more finding(s) left out" in body

    def test_skips_when_a_review_with_our_marker_is_already_present(
        self, mock_request: MagicMock, mock_paginated: MagicMock
    ) -> None:
        # Post-then-crash idempotency: an app-bot review already carrying this run's marker means we
        # posted but didn't record the watermark, so the retry must post neither a second review nor
        # the promo. (Only bot reviews count — a pasted marker in a human review must not match.)
        _wire_readbacks(
            mock_paginated,
            reviews=[{"body": "an earlier review\n\nmarker-xyz", "user": {"login": "posthog[bot]", "type": "Bot"}}],
        )

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
        mock_report.report_markdown = "# PostHog Review"
        mock_report_cls.objects.for_team.return_value.get.return_value = mock_report

    @parameterized.expand(
        [
            # A valid finding on an off-diff line resolves zero inline comments, but the review (its body
            # carries it in the "Other findings" section) must still post, not be silently dropped.
            ("all_off_diff", [240], 0, False, False),
            ("mixed", [1, 240], 1, False, False),
            ("all_inline", [1], 1, False, True),
            ("all_inline_with_a_body_note", [1], 1, True, False),
        ]
    )
    @patch(_POST)
    @patch(_LOAD_FINDINGS)
    @patch(_REPORT)
    def test_review_body_depends_on_which_findings_post_inline(
        self,
        _name: str,
        finding_lines: list[int],
        expected_comments: int,
        always_post_body: bool,
        expect_marker_only: bool,
        mock_report_cls: MagicMock,
        mock_load: MagicMock,
        mock_post: MagicMock,
    ) -> None:
        self._wire_report(mock_report_cls)
        mock_load.return_value = [
            (_finding().model_copy(update={"lines": [LineRange(start=line, end=line)]}), _verdict())
            for line in finding_lines
        ]
        pr_files = [
            PRFile(
                filename="src/auth.py",
                status="modified",
                additions=1,
                deletions=0,
                changes=[PRFileUpdate(type="addition", new_start_line=1, new_end_line=1, code="x")],
            )
        ]

        outcome = publish_review(
            owner="o",
            repo="r",
            pr_number=1,
            team_id=1,
            report_id="rep",
            run_index=1,
            pr_files=pr_files,
            token="t",
            head_sha="sha",
            post_promo=False,
            published_priorities=_SHOULD_FIX_PUBLISHED,
            always_post_body=always_post_body,
        )

        assert outcome.posted is True
        mock_post.assert_called_once()
        assert len(mock_post.call_args.args[4]) == expected_comments
        marker = mock_post.call_args.kwargs["marker"]
        assert marker in mock_post.call_args.args[3]
        assert mock_post.call_args.kwargs["inline_body"] == (marker if expect_marker_only else None)

    @patch(_POST)
    @patch(_LOAD_FINDINGS)
    @patch(_REPORT)
    def test_skips_when_only_consider_findings(
        self, mock_report_cls: MagicMock, mock_load: MagicMock, mock_post: MagicMock
    ) -> None:
        # Below the should_fix threshold: a run whose only valid finding is `consider` has
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
            published_priorities=_SHOULD_FIX_PUBLISHED,
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
            published_priorities=_SHOULD_FIX_PUBLISHED,
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
            [(_finding(priority=base), _verdict(adjusted_priority=adjusted))], diff_lines, _SHOULD_FIX_PUBLISHED
        )

        assert len(comments) == expected_count
        if expected_count:
            assert "**Should fix**" in comments[0]["body"]  # the emitted comment displays the effective priority

    @parameterized.expand(
        [
            ("range_fully_on_the_diff", {240, 241, 242}, True),
            # The end line is off the diff, so the comment covers only line 240. GitHub would apply
            # the three-line replacement to that one line and corrupt the file.
            ("range_partly_off_the_diff", {240}, False),
        ]
    )
    def test_suggestion_block_posts_only_when_the_comment_covers_the_finding_range(
        self, _name: str, diff_line_numbers: set[int], expect_suggestion: bool
    ) -> None:
        finding = _finding().model_copy(
            update={
                "lines": [LineRange(start=240, end=242)],
                "suggestion": "",
                "suggestion_code": "a = 1\nb = 2\nc = 3",
            }
        )
        comments = _build_inline_comments(
            [(finding, _verdict())], {"src/auth.py": diff_line_numbers}, _SHOULD_FIX_PUBLISHED
        )

        assert len(comments) == 1
        assert ("```suggestion\na = 1\nb = 2\nc = 3\n```" in comments[0]["body"]) is expect_suggestion
        assert "**Suggested fix**" not in comments[0]["body"]


class TestFormatIssueComment:
    @parameterized.expand(
        [
            (IssuePriority.MUST_FIX, "**Must fix**"),
            (IssuePriority.SHOULD_FIX, "**Should fix**"),
            (IssuePriority.CONSIDER, "**Consider**"),
        ]
    )
    def test_severity_line_tracks_priority(self, priority: IssuePriority, label: str) -> None:
        body = _format_issue_comment(_finding(priority=priority), _verdict())

        assert f"{label} · bug" in body

    def test_layout_is_title_severity_issue_fix_without_validator_notes(self) -> None:
        finding = _finding()
        body = _format_issue_comment(finding, _verdict())

        assert body.split("\n", 1)[0] == f"### {finding.title}"
        assert body.index("**Should fix**") < body.index(finding.body) < body.index("**Suggested fix**")
        assert "reason" not in body
        assert "<details>" not in body and "![" not in body

    def test_carries_the_self_detection_marker_for_the_resolution_stage(self) -> None:
        # The resolution stage's `_source_rank` recognizes ReviewHog's own threads by this hidden marker
        # in the opening comment. Drop it here and every ReviewHog thread misfiles under the other-bot
        # triage tier — the exact dead-code gap this guards against, now that both sides share the constant.
        assert REVIEW_HOG_FINDING_MARKER in _format_issue_comment(_finding(), _verdict())
