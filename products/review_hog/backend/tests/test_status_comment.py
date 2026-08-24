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
    RESOLUTION_SECTION_START,
    FinalizeStatusCommentInput,
    _splice_resolution_section,
    ensure_status_comment,
    fail_status_comment,
    finalize_status_comment,
    maybe_refresh_status_comment,
    render_final_body,
    render_in_progress_body,
    render_resolution_final_section,
    render_resolution_progress_section,
    status_marker,
    update_resolution_status_comment,
)
from products.review_hog.backend.temporal.activities import _fail_run

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
                ["Nothing worth raising this time, so here's a calming picture instead:", "![", "pr-assets"],
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

    @parameterized.expand(
        [
            # Whose settings gated the run must be named truthfully: blaming "the author's" settings
            # for a requester-gated run is the exact misattribution this wording exists to fix, and
            # the defensive default variant has no settings page to point at.
            ("author", 'the author\'s "Should fix" urgency threshold in their ReviewHog settings'),
            ("override", 'the requester\'s "Should fix" urgency threshold in their ReviewHog settings'),
            ("default", 'the default "Should fix" urgency threshold,'),
            # An unknown future value must degrade to the author wording, not crash the comment.
            ("mystery", 'the author\'s "Should fix" urgency threshold in their ReviewHog settings'),
        ]
    )
    def test_held_back_sentence_attributes_the_gating_threshold(self, resolved_from: str, expected: str) -> None:
        body = render_final_body(
            "rid",
            counts={IssuePriority.MUST_FIX: 0, IssuePriority.SHOULD_FIX: 0, IssuePriority.CONSIDER: 2},
            published_count=0,
            held_back_count=2,
            threshold=IssuePriority.SHOULD_FIX,
            review_url=None,
            resolved_from=resolved_from,
            report_url="https://ph.test/project/1/code-review?review=rid",
        )
        assert f"2 findings stayed below {expected}" in body, body
        # Held-back findings are otherwise invisible to the author — the comment must not dead-end.
        assert "[View them in PostHog](https://ph.test/project/1/code-review?review=rid)" in body

    @patch(f"{_MODULE}.random.choice", return_value=("https://example.test/dog.png", "A happy dog"))
    def test_uses_the_randomly_selected_clean_review_media(self, mock_choice: MagicMock) -> None:
        body = render_final_body(
            "rid",
            counts={IssuePriority.MUST_FIX: 0, IssuePriority.SHOULD_FIX: 0, IssuePriority.CONSIDER: 0},
            published_count=0,
            held_back_count=0,
            threshold=IssuePriority.SHOULD_FIX,
            review_url=None,
        )

        assert "![A happy dog](https://example.test/dog.png)" in body
        mock_choice.assert_called_once()


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
            FinalizeStatusCommentInput(
                team_id=self.team.id,
                report_id=report_id,
                run_index=1,
                urgency_threshold=IssuePriority.SHOULD_FIX.value,
                review_url="https://g/review",
            )
        )

        assert _patches(mock_request) == ["/repos/o/r/issues/comments/555"]
        body = mock_request.call_args.kwargs["json"]["body"]
        assert "Found **1 must fix**, **0 should fix**, **2 consider**" in body
        assert "Published 1 finding ([view the review](https://g/review))" in body
        assert '2 findings stayed below the author\'s "Should fix" urgency threshold' in body
        # The held-back link into the app. `?review=<report id>` is a permanent public contract
        # (baked into GitHub comments) — the frontend's URL sync accepts exactly this param.
        assert f"/project/{self.team.id}/code-review?review={report_id})" in body

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


class TestResolutionSection:
    def test_splice_appends_then_replaces_in_place(self) -> None:
        # The section is edited into the shared status comment on every settled thread; a broken
        # splice would either stack one section per update or eat the review's own body above it.
        review_body = "### review outcome\n\nFound things.\n\n" + status_marker("rid")
        first = _splice_resolution_section(
            review_body, render_resolution_progress_section(done=0, total=3, fixed=0, left_for_you=0)
        )
        assert "### review outcome" in first
        assert "Resolving comments: 0/3" in first

        second = _splice_resolution_section(
            first, render_resolution_progress_section(done=2, total=3, fixed=1, left_for_you=1)
        )

        assert "### review outcome" in second
        assert status_marker("rid") in second
        assert second.count(RESOLUTION_SECTION_START) == 1
        assert "Resolving comments: 2/3 · 1 fixed, 1 left for you" in second
        assert "0/3" not in second

    def test_final_section_buckets_outcomes_and_names_failures(self) -> None:
        # The closing tally is the PR author's durable record: already_fixed and obsolete collapse
        # into one bucket, and threads the run could not handle must be named, never silent.
        section = render_resolution_final_section(
            outcomes={"fixed": 2, "wont_fix": 1, "already_fixed": 1, "obsolete": 1, "escalate": 1},
            failed_turns=2,
        )
        assert "Resolved comments: 2 fixed, 1 declined, 2 already settled, 1 left for you" in section
        assert "couldn't handle 2" in section


@patch(_INTEGRATION)
@patch(_PAGINATED)
@patch(_REQUEST)
class TestUpdateResolutionStatusComment(BaseTest):
    def _report(self) -> ReviewReport:
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        return ReviewReport.objects.for_team(self.team.id).get(id=report_id)

    def test_standalone_run_creates_the_comment_on_demand(
        self, mock_request: MagicMock, mock_paginated: MagicMock, mock_integration: MagicMock
    ) -> None:
        # A standalone resolution targets a PR that never got a review comment — without the
        # create-on-demand path the run has no GitHub-visible progress at all.
        _wire_auth(mock_integration)
        mock_paginated.return_value = iter([])
        mock_request.return_value.json.return_value = {"id": 888}
        report = self._report()

        update_resolution_status_comment(
            self.team.id, str(report.id), render_resolution_progress_section(done=0, total=3, fixed=0, left_for_you=0)
        )

        assert _posts(mock_request) == ["/repos/o/r/issues/123/comments"]
        posted = next(c for c in mock_request.call_args_list if c.args[0] == "POST")
        assert "Resolving comments: 0/3" in posted.kwargs["json"]["body"]
        assert status_marker(str(report.id)) in posted.kwargs["json"]["body"]
        report.refresh_from_db()
        assert report.status_comment_id == 888

    def test_chained_run_extends_the_existing_review_comment(
        self, mock_request: MagicMock, mock_paginated: MagicMock, mock_integration: MagicMock
    ) -> None:
        # One ReviewHog voice per PR: the resolution section lands inside the review's comment via
        # edit (no new comment, no notification), with the review's own body preserved above it.
        _wire_auth(mock_integration)
        report = self._report()
        report.status_comment_id = 777
        report.save(update_fields=["status_comment_id"])
        get_response = MagicMock()
        get_response.json.return_value = {"body": "### reviewed\n\n" + status_marker(str(report.id))}
        mock_request.side_effect = [get_response, MagicMock()]

        update_resolution_status_comment(
            self.team.id, str(report.id), render_resolution_progress_section(done=1, total=3, fixed=1, left_for_you=0)
        )

        assert _posts(mock_request) == []
        assert _patches(mock_request) == ["/repos/o/r/issues/comments/777"]
        patched = mock_request.call_args_list[1].kwargs["json"]["body"]
        assert "### reviewed" in patched
        assert "Resolving comments: 1/3 · 1 fixed" in patched

    def test_empty_existing_body_keeps_the_marker_for_recovery(
        self, mock_request: MagicMock, mock_paginated: MagicMock, mock_integration: MagicMock
    ) -> None:
        # An empty existing comment body must not drop the status marker: if status_comment_id is
        # ever lost, _find_marker_comment re-adopts the comment by that marker, so the spliced body
        # has to carry it even when there is nothing to splice into (else recovery posts a duplicate).
        _wire_auth(mock_integration)
        report = self._report()
        report.status_comment_id = 777
        report.save(update_fields=["status_comment_id"])
        get_response = MagicMock()
        get_response.json.return_value = {"body": ""}
        mock_request.side_effect = [get_response, MagicMock()]

        update_resolution_status_comment(
            self.team.id, str(report.id), render_resolution_progress_section(done=1, total=3, fixed=1, left_for_you=0)
        )

        assert _patches(mock_request) == ["/repos/o/r/issues/comments/777"]
        patched = mock_request.call_args_list[1].kwargs["json"]["body"]
        assert status_marker(str(report.id)) in patched

    @patch(f"{_MODULE}.Integration")
    def test_pinned_integration_row_skips_the_selection_probe(
        self,
        mock_integration_model: MagicMock,
        mock_request: MagicMock,
        mock_paginated: MagicMock,
        mock_integration: MagicMock,
    ) -> None:
        # A resolution run pins its installation once and refreshes after every thread; passing the
        # pinned row must re-mint the token from it, never re-run first_for_team_repository (a
        # GET /repos/... per integration tried) on each refresh.
        mock_integration.return_value.get_access_token.return_value = "tok"
        mock_integration.return_value.github_installation_id = "inst-1"
        report = self._report()
        report.status_comment_id = 777
        report.save(update_fields=["status_comment_id"])
        get_response = MagicMock()
        get_response.json.return_value = {"body": "### reviewed\n\n" + status_marker(str(report.id))}
        mock_request.side_effect = [get_response, MagicMock()]

        update_resolution_status_comment(
            self.team.id,
            str(report.id),
            render_resolution_progress_section(done=1, total=3, fixed=1, left_for_you=0),
            integration_row_id=42,
        )

        mock_integration.first_for_team_repository.assert_not_called()
        mock_integration_model.objects.get.assert_called_once_with(id=42, team_id=self.team.id)
        assert _patches(mock_request) == ["/repos/o/r/issues/comments/777"]


class TestFailRun(BaseTest):
    def test_returns_the_report_to_rest_even_without_a_status_comment(self) -> None:
        # Publishing runs defer finalize's idle write to the publish stage, so the failure path must
        # restore rest itself or a dead run reads as in-progress in the UI until the staleness
        # cutoff. A report with no status comment (nothing to edit on GitHub) must still go idle.
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        assert ReviewReport.objects.for_team(self.team.id).get(id=report_id).status == ReviewReport.Status.ACTIVE

        _fail_run(self.team.id, report_id)

        assert ReviewReport.objects.for_team(self.team.id).get(id=report_id).status == ReviewReport.Status.IDLE
