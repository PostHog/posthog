from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.persistence import persist_findings, persist_verdict, upsert_review_report
from products.review_hog.backend.reviewer.status_comment import (
    ensure_status_comment,
    fail_status_comment,
    finalize_status_comment,
    maybe_refresh_status_comment,
    render_final_body,
    render_in_progress_body,
    status_marker,
)

_MODULE = "products.review_hog.backend.reviewer.status_comment"
_REQUEST = f"{_MODULE}.github_api_request"
_PAGINATED = f"{_MODULE}.github_api_get_paginated"
_INTEGRATION = f"{_MODULE}.GitHubIntegration"


_STAGE_LINE_CASES: list[tuple[dict[str, Any] | None, str]] = [
    (None, "Step 1/6 · Preparing the diff"),
    ({"review_stage": "chunking", "done": None, "total": None}, "Step 1/6 · Splitting into chunks"),
    ({"review_stage": "reviewing", "done": 7, "total": 18}, "Step 3/6 · Running review passes · 7/18"),
    ({"review_stage": "validating", "done": 2, "total": None}, "Step 5/6 · Validating findings"),
]


class TestRenderInProgressBody:
    @parameterized.expand(_STAGE_LINE_CASES)
    def test_renders_the_stage_line_and_marker(self, progress: dict[str, Any] | None, expected_line: str) -> None:
        body = render_in_progress_body("rid", progress)
        assert f"**{expected_line}**" in body
        assert status_marker("rid") in body  # the marker is what makes edit-in-place reuse possible


class TestRenderFinalBody:
    @parameterized.expand(
        [
            # All published: full counts + the review link, no held-back line.
            (
                {IssuePriority.MUST_FIX: 1, IssuePriority.SHOULD_FIX: 2, IssuePriority.CONSIDER: 5},
                8,
                0,
                IssuePriority.CONSIDER,
                "https://g/review",
                [
                    "Found **1 must fix**, **2 should fix**, **5 consider**",
                    "Published 8 findings ([view the review](https://g/review))",
                ],
                ["stayed below"],
            ),
            # The key case: some findings held back — the comment must still show everything found.
            (
                {IssuePriority.MUST_FIX: 0, IssuePriority.SHOULD_FIX: 2, IssuePriority.CONSIDER: 5},
                2,
                5,
                IssuePriority.SHOULD_FIX,
                "https://g/review",
                [
                    "Found **0 must fix**, **2 should fix**, **5 consider**",
                    "Published 2 findings",
                    '5 findings stayed below the author\'s "Should fix" urgency threshold',
                ],
                [],
            ),
            # Zero publishable: explicit closure instead of silence, no "Published" line.
            (
                {IssuePriority.MUST_FIX: 0, IssuePriority.SHOULD_FIX: 0, IssuePriority.CONSIDER: 5},
                0,
                5,
                IssuePriority.SHOULD_FIX,
                None,
                ["Found **0 must fix**, **0 should fix**, **5 consider**", "5 findings stayed below"],
                ["Published"],
            ),
            # Nothing found at all.
            (
                {IssuePriority.MUST_FIX: 0, IssuePriority.SHOULD_FIX: 0, IssuePriority.CONSIDER: 0},
                0,
                0,
                IssuePriority.SHOULD_FIX,
                None,
                ["Found no issues worth raising, so no review was posted."],
                ["Published", "stayed below"],
            ),
            # Posted on a prior crashed attempt (marker skip): published, but no link to render.
            (
                {IssuePriority.MUST_FIX: 1, IssuePriority.SHOULD_FIX: 0, IssuePriority.CONSIDER: 0},
                1,
                0,
                IssuePriority.SHOULD_FIX,
                None,
                ["Published 1 finding."],
                ["view the review"],
            ),
        ]
    )
    def test_shows_full_counts_and_the_published_vs_held_back_split(
        self, counts, published_count, held_back_count, threshold, review_url, expected, absent
    ) -> None:
        body = render_final_body(
            "rid",
            counts=counts,
            published_count=published_count,
            held_back_count=held_back_count,
            threshold=threshold,
            review_url=review_url,
        )
        for fragment in expected:
            assert fragment in body, f"missing {fragment!r} in:\n{body}"
        for fragment in absent:
            assert fragment not in body, f"unexpected {fragment!r} in:\n{body}"
        assert status_marker("rid") in body


def _pr_metadata(pr_number: int = 123) -> PRMetadata:
    return PRMetadata(
        number=pr_number,
        title="t",
        state="open",
        draft=False,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        author="a",
        base_branch="main",
        head_branch="feat",
        head_sha="sha-1",
        commits=1,
        additions=1,
        deletions=0,
        changed_files=1,
    )


def _wire_auth(mock_integration: MagicMock) -> None:
    github = MagicMock()
    github.get_access_token.return_value = "tok"
    github.github_installation_id = "inst-1"
    mock_integration.first_for_team_repository.return_value = github


def _patches(mock_request: MagicMock) -> list[str]:
    return [c.args[1] for c in mock_request.call_args_list if c.args[0] == "PATCH"]


def _posts(mock_request: MagicMock) -> list[str]:
    return [c.args[1] for c in mock_request.call_args_list if c.args[0] == "POST"]


@patch(_INTEGRATION)
@patch(_PAGINATED)
@patch(_REQUEST)
class TestEnsureStatusComment(BaseTest):
    def _report(self) -> ReviewReport:
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        return ReviewReport.objects.for_team(self.team.id).get(id=report_id)

    def test_posts_a_fresh_comment_and_saves_its_id(
        self, mock_request: MagicMock, mock_paginated: MagicMock, mock_integration: MagicMock
    ) -> None:
        _wire_auth(mock_integration)
        mock_paginated.return_value = iter([])
        mock_request.return_value.json.return_value = {"id": 777}
        report = self._report()

        ensure_status_comment(self.team.id, str(report.id))

        assert _posts(mock_request) == ["/repos/o/r/issues/123/comments"]
        report.refresh_from_db()
        assert report.status_comment_id == 777
        assert report.status_comment_edited_at is not None

    def test_reuses_the_stored_comment_without_posting_or_scanning(
        self, mock_request: MagicMock, mock_paginated: MagicMock, mock_integration: MagicMock
    ) -> None:
        # A re-review must edit the same comment, not stack a new one (new comments notify everyone).
        _wire_auth(mock_integration)
        report = self._report()
        report.status_comment_id = 555
        report.save(update_fields=["status_comment_id"])

        ensure_status_comment(self.team.id, str(report.id))

        assert _patches(mock_request) == ["/repos/o/r/issues/comments/555"]
        assert _posts(mock_request) == []
        mock_paginated.assert_not_called()

    def test_adopts_a_marker_comment_left_by_a_crashed_prior_run(
        self, mock_request: MagicMock, mock_paginated: MagicMock, mock_integration: MagicMock
    ) -> None:
        # Crash between POST and saving the id: the marker scan must find the orphan, or every retry
        # posts a duplicate status comment. It must only adopt app-bot comments — a human comment
        # carrying a pasted marker would otherwise get clobbered by the next edit.
        _wire_auth(mock_integration)
        report = self._report()
        marker = status_marker(str(report.id))
        mock_paginated.return_value = iter(
            [
                {"id": 1, "body": "unrelated", "user": {"login": "someone", "type": "User"}},
                {"id": 7, "body": f"pasted copy: {marker}", "user": {"login": "prankster", "type": "User"}},
                {"id": 888, "body": f"hello\n{marker}", "user": {"login": "posthog[bot]", "type": "Bot"}},
            ]
        )

        ensure_status_comment(self.team.id, str(report.id))

        assert _patches(mock_request) == ["/repos/o/r/issues/comments/888"]
        assert _posts(mock_request) == []
        report.refresh_from_db()
        assert report.status_comment_id == 888


@patch(_INTEGRATION)
@patch(_REQUEST)
class TestMaybeRefreshStatusComment(BaseTest):
    def _report(self, *, comment_id: int | None, edited_ago: timedelta | None) -> ReviewReport:
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        report = ReviewReport.objects.for_team(self.team.id).get(id=report_id)
        report.status_comment_id = comment_id
        report.status_comment_edited_at = timezone.now() - edited_ago if edited_ago is not None else None
        report.save(update_fields=["status_comment_id", "status_comment_edited_at"])
        return report

    def test_skips_a_run_without_a_status_comment(self, mock_request: MagicMock, mock_integration: MagicMock) -> None:
        # The eval / CLI / branch-target bail: those runs must keep zero GitHub footprint.
        report = self._report(comment_id=None, edited_ago=None)

        maybe_refresh_status_comment(self.team.id, str(report.id))

        mock_request.assert_not_called()
        mock_integration.first_for_team_repository.assert_not_called()

    def test_debounces_edits_within_the_interval(self, mock_request: MagicMock, mock_integration: MagicMock) -> None:
        # The (perspective, chunk) fan-out calls this per finished unit; without the claim every unit
        # would burn a GitHub edit.
        report = self._report(comment_id=555, edited_ago=timedelta(seconds=5))

        maybe_refresh_status_comment(self.team.id, str(report.id))

        mock_request.assert_not_called()

    def test_edits_once_the_interval_has_passed(self, mock_request: MagicMock, mock_integration: MagicMock) -> None:
        _wire_auth(mock_integration)
        report = self._report(comment_id=555, edited_ago=timedelta(minutes=5))
        before = report.status_comment_edited_at
        assert before is not None

        maybe_refresh_status_comment(self.team.id, str(report.id))

        assert _patches(mock_request) == ["/repos/o/r/issues/comments/555"]
        report.refresh_from_db()
        assert report.status_comment_edited_at is not None and report.status_comment_edited_at > before


@patch(_INTEGRATION)
@patch(_REQUEST)
class TestFinalizeStatusComment(BaseTest):
    def _issue(self, issue_id: str, priority: IssuePriority) -> Issue:
        return Issue(
            id=issue_id,
            title="t",
            file="a.py",
            lines=[LineRange(start=10)],
            issue="problem",
            suggestion="fix",
            priority=priority,
            source_perspective="Logic & Correctness",
        )

    def test_counts_use_effective_priority_and_split_on_the_threshold(
        self, mock_request: MagicMock, mock_integration: MagicMock
    ) -> None:
        # The validator's priority override must count at its adjusted level — the same rule publish
        # gates on — or the comment's numbers disagree with what actually landed on the PR.
        _wire_auth(mock_integration)
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        report = ReviewReport.objects.for_team(self.team.id).get(id=report_id)
        report.status_comment_id = 555
        report.save(update_fields=["status_comment_id"])
        issues = [
            self._issue("1-1-1", IssuePriority.MUST_FIX),
            self._issue("1-1-2", IssuePriority.SHOULD_FIX),
            self._issue("1-1-3", IssuePriority.CONSIDER),
        ]
        persist_findings(team_id=self.team.id, report_id=report_id, issues=issues, run_index=1)
        # The validator downgrades the should_fix to consider; the must_fix and consider keep theirs.
        verdicts = [
            (issues[0], IssueValidation(is_valid=True, argumentation="a")),
            (issues[1], IssueValidation(is_valid=True, argumentation="a", adjusted_priority=IssuePriority.CONSIDER)),
            (issues[2], IssueValidation(is_valid=True, argumentation="a")),
        ]
        for issue, validation in verdicts:
            persist_verdict(team_id=self.team.id, report_id=report_id, issue=issue, validation=validation, run_index=1)

        finalize_status_comment(
            self.team.id,
            report_id,
            run_index=1,
            urgency_threshold=IssuePriority.SHOULD_FIX.value,
            review_url="https://g/review",
        )

        assert _patches(mock_request) == ["/repos/o/r/issues/comments/555"]
        body = mock_request.call_args.kwargs["json"]["body"]
        assert "Found **1 must fix**, **0 should fix**, **2 consider**" in body
        assert "Published 1 finding ([view the review](https://g/review))" in body
        assert '2 findings stayed below the author\'s "Should fix" urgency threshold' in body

    def test_failed_edit_rewrites_the_comment_as_failed(
        self, mock_request: MagicMock, mock_integration: MagicMock
    ) -> None:
        # A dead run must not read as forever in progress on the PR.
        _wire_auth(mock_integration)
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        report = ReviewReport.objects.for_team(self.team.id).get(id=report_id)
        report.status_comment_id = 555
        report.save(update_fields=["status_comment_id"])

        fail_status_comment(self.team.id, report_id)

        assert _patches(mock_request) == ["/repos/o/r/issues/comments/555"]
        body = mock_request.call_args.kwargs["json"]["body"]
        assert "couldn't finish this review" in body
