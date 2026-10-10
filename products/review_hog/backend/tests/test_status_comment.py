from collections.abc import Callable
from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH
from products.review_hog.backend.reviewer.fingerprint import ReviewHogMarker
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.models.thread_resolution import CommitHold
from products.review_hog.backend.reviewer.persistence import persist_findings, persist_verdict, upsert_review_report
from products.review_hog.backend.reviewer.review_design import REVIEW_DESIGN_PIPELINE, REVIEW_DESIGN_SINGLE_AGENT
from products.review_hog.backend.reviewer.status_comment import (
    RESOLUTION_NOTHING_TO_DO,
    FinalizeStatusCommentInput,
    ResolutionStep,
    TurnFacts,
    _splice_resolution_section,
    ensure_status_comment,
    fail_status_comment,
    finalize_status_comment,
    maybe_refresh_status_comment,
    render_failed_body,
    render_final_body,
    render_in_progress_body,
    resolution_failed_step,
    resolution_final_step,
    resolution_held_step,
    resolution_progress_step,
    status_marker,
    update_resolution_status_comment,
)
from products.review_hog.backend.reviewer.tools.issue_deduplicator import AlreadyRaised
from products.review_hog.backend.reviewer.tools.single_agent_review import FlashTurnStats
from products.review_hog.backend.temporal.activities import _fail_run

_MODULE = "products.review_hog.backend.reviewer.status_comment"
_REQUEST = f"{_MODULE}.github_api_request"
_PAGINATED = f"{_MODULE}.github_api_get_paginated"
_INTEGRATION = f"{_MODULE}.GitHubIntegration"

_SHA = "b81c2e1f00d"
_PERSPECTIVES = (
    "review-hog-perspective-logic-correctness",
    "review-hog-perspective-contracts-security",
    "review-hog-perspective-performance-reliability",
)
_DEEP_DONE_FACTS = TurnFacts(
    files_reviewed=14,
    chunk_count=3,
    perspectives=_PERSPECTIVES,
    planned_passes=9,
    passes_done=9,
    pass_issues=14,
    blind_spot_done=3,
    blind_spot_issues=2,
    merged=9,
    judged=9,
    kept=4,
)
_FLASH_STATS = FlashTurnStats(
    cap=5,
    lens_part_count=2,
    reviewable_lines=900,
    candidates={"main": 4, "performance_reliability": 3, "contracts_security": 2},
    must_fix={},
    after_dedup=6,
    dropped={"dedup_anchor": 2, "old_code": 1, "cap": 1},
    kept=5,
    dedup_fell_back=False,
)
_NO_COUNTS = dict.fromkeys(IssuePriority, 0)


def _deep_done(**overrides) -> str:
    kwargs = {
        "counts": {IssuePriority.MUST_FIX: 1, IssuePriority.SHOULD_FIX: 2, IssuePriority.CONSIDER: 1},
        "published_count": 3,
        "held_back_count": 1,
        "threshold": IssuePriority.SHOULD_FIX,
        "review_url": "https://g/review",
        "report_url": "https://ph.test/r",
        "head_sha": _SHA,
        "facts": _DEEP_DONE_FACTS,
        **overrides,
    }
    return render_final_body("rid", **kwargs)


def _standard_done(published_count: int, flash: FlashTurnStats | None) -> str:
    counts = {**_NO_COUNTS, IssuePriority.MUST_FIX: published_count}
    return render_final_body(
        "rid",
        counts=counts,
        published_count=published_count,
        held_back_count=0,
        threshold=IssuePriority.CONSIDER,
        review_url=None,
        review_mode=REVIEW_MODE_FLASH,
        review_design=REVIEW_DESIGN_SINGLE_AGENT,
        head_sha=_SHA,
        facts=TurnFacts(files_reviewed=14),
        flash=flash,
    )


_PHASE_CASES: list[tuple[str, Callable[[], str], list[str], list[str]]] = [
    (
        "deep_kickoff",
        lambda: render_in_progress_body("rid", None, head_sha=_SHA),
        [
            "### \U0001f994 PostHog Review · Deep · reviewing `b81c2e1`",
            "Reviewing · step 1 of 7",
            "| Prepare the diff | ⏳ Running |  |",
            "| Publish | ⏸ Waiting |  |",
            "<sub>This comment updates as the review runs.</sub>",
        ],
        ["Resolve comments"],
    ),
    (
        "deep_running",
        lambda: render_in_progress_body(
            "rid",
            {"review_stage": "reviewing", "done": 7, "total": 12},
            head_sha=_SHA,
            facts=TurnFacts(
                files_reviewed=14,
                chunk_count=3,
                perspectives=_PERSPECTIVES,
                planned_passes=9,
                passes_done=7,
                pass_issues=11,
            ),
        ),
        [
            "Reviewing · step 3 of 7",
            "| Prepare the diff | ✅ Done | 14 files, 3 chunks |",
            "| Pick perspectives | ✅ Done | Logic, Security, Performance |",
            "| Review passes | ⏳ 7/9 | 11 issues |",
            "| Blind-spot check | ⏸ Waiting |  |",
        ],
        [],
    ),
    (
        # The blind-spot checks run inside the same "reviewing" stage, once the planned passes finish.
        "deep_blind_spot",
        lambda: render_in_progress_body(
            "rid",
            {"review_stage": "reviewing", "done": 10, "total": 12},
            facts=TurnFacts(chunk_count=3, planned_passes=9, passes_done=9, pass_issues=14, blind_spot_done=1),
        ),
        ["Reviewing · step 4 of 7", "| Review passes | ✅ 9/9 | 14 issues |", "| Blind-spot check | ⏳ 1/3 |"],
        [],
    ),
    (
        "deep_failed",
        lambda: render_failed_body(
            "rid", head_sha=_SHA, progress={"review_stage": "validating", "done": 3, "total": 9}, facts=_DEEP_DONE_FACTS
        ),
        [
            "### \U0001f994 PostHog Review · Deep · couldn't finish reviewing `b81c2e1`",
            'The review failed at "Validate". Ask for a Deep review again to retry.',
            "| Merge overlapping findings | ✅ Done | 16 → 9 |",
            "| Validate | ❌ Failed |  |",
            "| Publish | Skipped |  |",
        ],
        ["⏳", "updates as the review runs"],
    ),
    (
        "deep_done",
        _deep_done,
        [
            "### \U0001f994 PostHog Review · Deep · reviewed `b81c2e1`",
            "Posted 3 findings: 1 Must fix, 2 Should fix.",
            "| Blind-spot check | ✅ 3/3 | +2 issues (16 in total) |",
            "| Merge overlapping findings | ✅ Done | 16 → 9 |",
            "| Validate | ✅ 9/9 | 4 kept, 5 dismissed |",
            '| Publish | ✅ Done | 3 posted ([view review](https://g/review)) · 1 Consider held back by the author\'s "Should fix" threshold ([view in PostHog](https://ph.test/r)) |',
        ],
        ["⏳", "⏸", "Resolve comments", "updates as the review runs"],
    ),
    (
        "standard_running",
        lambda: render_in_progress_body(
            "rid", None, review_mode=REVIEW_MODE_FLASH, review_design=REVIEW_DESIGN_SINGLE_AGENT
        ),
        [
            "### \U0001f994 PostHog Review · Standard · reviewing this pull request",
            "Reviewing · step 2 of 4",
            "| Main review and lenses | ⏳ Running |  |",
        ],
        ["Pick perspectives"],
    ),
    (
        "standard_done",
        lambda: _standard_done(5, _FLASH_STATS),
        [
            "| Prepare the diff | ✅ Done | 14 files |",
            "| Main review + 4 lenses | ✅ 5/5 | 9 findings |",
            "| Merge and cap | ✅ Done | 9 → 5 (repeats, unchanged code, limit) |",
            "| Publish | ✅ Done | 5 posted |",
        ],
        ["Resolve comments"],
    ),
    (
        "standard_clean",
        lambda: _standard_done(0, None),
        ["Nothing worth raising.", "| Publish | ✅ Done | Nothing to post |"],
        ["!["],
    ),
    (
        # An older Standard turn ran the full pipeline, so the rows follow the design, not the mode.
        "standard_on_the_pipeline",
        lambda: render_in_progress_body(
            "rid", None, review_mode=REVIEW_MODE_FLASH, review_design=REVIEW_DESIGN_PIPELINE
        ),
        ["PostHog Review · Standard · reviewing", "| Pick perspectives | ⏸ Waiting |  |"],
        ["Main review"],
    ),
]


class TestStatusTable:
    @parameterized.expand(_PHASE_CASES)
    def test_renders_each_phase_as_one_table(
        self, _name: str, render: Callable[[], str], expected: list[str], absent: list[str]
    ) -> None:
        body = render()
        for fragment in expected:
            assert fragment in body, f"missing {fragment!r} in:\n{body}"
        for fragment in absent:
            assert fragment not in body, f"unexpected {fragment!r} in:\n{body}"
        assert status_marker("rid") in body  # the marker is what makes edit-in-place reuse possible

    @parameterized.expand(
        [
            # Whose settings gated the run must be named truthfully: blaming "the author's" settings
            # for a requester-gated run is the exact misattribution this wording exists to fix.
            ("author", "the author's"),
            ("override", "the requester's"),
            ("default", "the default"),
            # An unknown future value must degrade to the author wording, not crash the comment.
            ("mystery", "the author's"),
        ]
    )
    def test_held_back_cell_attributes_the_gating_threshold(self, resolved_from: str, expected: str) -> None:
        body = _deep_done(
            counts={**_NO_COUNTS, IssuePriority.CONSIDER: 2},
            published_count=0,
            held_back_count=2,
            review_url=None,
            resolved_from=resolved_from,
            marker=ReviewHogMarker(version="reviewhog-flash-9-9", fingerprint="abc1234"),
        )
        assert "Nothing posted: 2 findings below the urgency threshold." in body
        assert (
            f'2 Consider held back by {expected} "Should fix" threshold ([view in PostHog](https://ph.test/r))' in body
        )
        # The version rides in a hidden HTML comment, so it adds no visible text to the PR.
        hidden = "<!-- reviewhog-version: reviewhog-flash-9-9 abc1234 -->"
        assert hidden in body
        assert "reviewhog-flash" not in body.replace(hidden, "")

    @parameterized.expand(
        [
            ("default_on", True, True),
            ("author_opted_out", False, False),
        ]
    )
    @patch(f"{_MODULE}.random.choice", return_value=("https://example.test/dog.png", "A happy dog"))
    def test_clean_review_media_follows_the_preference(
        self, _name: str, celebrate: bool, expect_media: bool, mock_choice: MagicMock
    ) -> None:
        body = _deep_done(counts=_NO_COUNTS, published_count=0, held_back_count=0, celebrate_clean_reviews=celebrate)

        assert "Nothing worth raising." in body
        assert ("![A happy dog](https://example.test/dog.png)" in body) is expect_media
        if expect_media:
            assert body.index("| Publish |") < body.index("![A happy dog]")

    @parameterized.expand(
        [
            # A clean turn posts no review, so the status comment is the only place the note can appear.
            ("clean_large_pr", 0, 4, True),
            ("large_pr_with_findings", 2, 4, True),
            ("normal_pr", 2, None, False),
        ]
    )
    def test_large_pr_note_shows_whether_or_not_a_review_posts(
        self, _name: str, must_fix: int, capped_lens_parts: int | None, expect_note: bool
    ) -> None:
        body = render_final_body(
            "rid",
            counts={**_NO_COUNTS, IssuePriority.MUST_FIX: must_fix},
            published_count=must_fix,
            held_back_count=0,
            threshold=IssuePriority.SHOULD_FIX,
            review_url=None,
            review_mode=REVIEW_MODE_FLASH,
            capped_lens_parts=capped_lens_parts,
        )

        note = "This pull request is large, so the review ran in 4 parts with less depth than usual."
        assert (note in body) is expect_note

    @parameterized.expand(
        [("clean_turn", 0, "Nothing new to raise."), ("turn_with_findings", 1, "Posted 1 finding: 1 Must fix.")]
    )
    def test_deep_lists_what_other_comments_already_raise(self, _name: str, must_fix: int, opening: str) -> None:
        raised = [
            AlreadyRaised(title=f"Problem {n}", level="P2", comment_id=100 + n, commenter="greptile-apps[bot]")
            for n in range(12)
        ]

        body = _deep_done(
            counts={**_NO_COUNTS, IssuePriority.MUST_FIX: must_fix},
            published_count=must_fix,
            held_back_count=0,
            raised_elsewhere=raised[:10],
            raised_elsewhere_count=len(raised),
            pr_url="https://github.com/o/r/pull/7",
        )

        # A Deep turn that only repeated other reviewers must say so instead of celebrating a clean PR.
        assert opening in body
        assert "![" not in body
        assert (
            "- **P2 · Problem 0**, raised by `greptile-apps[bot]` ([comment](https://github.com/o/r/pull/7#discussion_r100))"
            in body
        )
        assert "Problem 10" not in body
        assert "- and 2 more" in body


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

        ensure_status_comment(self.team.id, str(report.id), review_mode=REVIEW_MODE_FLASH)

        assert _posts(mock_request) == ["/repos/o/r/issues/123/comments"]
        assert mock_request.call_args.kwargs["json"]["body"].startswith(
            "### \U0001f994 PostHog Review · Standard · reviewing "
        )
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

        leaked = "ghs_" + "a" * 36
        finalize_status_comment(
            FinalizeStatusCommentInput(
                team_id=self.team.id,
                report_id=report_id,
                run_index=1,
                urgency_threshold=IssuePriority.SHOULD_FIX.value,
                review_url="https://g/review",
                raised_elsewhere=[
                    AlreadyRaised(title=f"Token {leaked} leaks", level="P1", comment_id=9, commenter="other[bot]")
                ],
                raised_elsewhere_count=1,
            )
        )

        assert _patches(mock_request) == ["/repos/o/r/issues/comments/555"]
        body = mock_request.call_args.kwargs["json"]["body"]
        assert "Posted 1 finding: 1 Must fix." in body
        # Titles in the already-raised list are model text, so a token quoted from sandbox output must not post.
        assert leaked not in body
        assert "**P1 · Token [redacted] leaks**" in body
        assert "| Validate | ✅ 3/3 | 3 kept, 0 dismissed |" in body
        assert '1 posted ([view review](https://g/review)) · 2 Consider held back by the author\'s "Should fix"' in body
        # The held-back link into the app. `?review=<report id>` is a permanent public contract
        # (baked into GitHub comments) — the frontend's URL sync accepts exactly this param.
        assert f"/project/{self.team.id}/code-review?review={report_id})" in body
        assert "Resolve comments" not in body

    def test_failed_edit_rewrites_the_comment_as_failed(
        self, mock_request: MagicMock, mock_integration: MagicMock
    ) -> None:
        # A dead run must not read as forever in progress on the PR.
        _wire_auth(mock_integration)
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        report = ReviewReport.objects.for_team(self.team.id).get(id=report_id)
        report.status_comment_id = 555
        report.head_sha = "b81c2e1f00d"
        report.save(update_fields=["status_comment_id", "head_sha"])

        fail_status_comment(
            self.team.id, report_id, review_mode=REVIEW_MODE_FLASH, review_design=REVIEW_DESIGN_SINGLE_AGENT
        )

        assert _patches(mock_request) == ["/repos/o/r/issues/comments/555"]
        body = mock_request.call_args.kwargs["json"]["body"]
        # The entry point threads the turn's mode and design into the renderer; a dropped kwarg here
        # would leave a dead Standard run reading as a Deep one, with the wrong rows.
        assert body.startswith("### \U0001f994 PostHog Review · Standard · couldn't finish reviewing `b81c2e1`")
        assert "| Main review and lenses | ❌ Failed |  |" in body
        # Only a Standard review runs again on its own, so only its failure points at the next push.
        assert 'failed at "Main review and lenses". It runs again on the next push to this pull request.' in body


class TestResolutionRow:
    @parameterized.expand(
        [
            (
                "running",
                resolution_progress_step(done=1, total=3, fixed=1, left_for_you=0),
                "| Resolve comments | ⏳ 1/3 | 1 fixed with a commit on your branch |",
                " Resolve is working through 3 comments.",
            ),
            (
                "done",
                resolution_final_step(outcomes={"fixed": 2, "escalate": 1}, failed_turns=0),
                "| Resolve comments | ✅ 3/3 | 2 fixed with commits on your branch, 1 left for you |",
                " Resolve pushed fixes for 2. 1 is left for you.",
            ),
            (
                "held_at_start",
                resolution_held_step(CommitHold.BRANCH_PROTECTED),
                "| Resolve comments | ⏭ Skipped | This branch is protected |",
                " Resolve did not run. A person decides what lands on a protected branch",
            ),
            (
                "held_mid_run",
                resolution_held_step(CommitHold.MERGE_QUEUE, done=2, total=5),
                "| Resolve comments | ⏹ Stopped | Stopped at 2/5: this pull request entered the merge queue |",
                " Resolve stopped. A fix commit would change what was submitted",
            ),
            (
                "failed",
                resolution_failed_step(done=1, total=3),
                "| Resolve comments | ❌ Failed | Stopped at 1/3 |",
                " Resolve stopped early.",
            ),
            (
                "nothing_to_do",
                RESOLUTION_NOTHING_TO_DO,
                "| Resolve comments | ✅ Done | No open threads to resolve |",
                "",
            ),
        ]
    )
    def test_splice_replaces_the_waiting_row_and_summary_in_place(
        self, _name: str, step: ResolutionStep, row: str, summary: str
    ) -> None:
        # The row is edited into the shared status comment on every settled thread; a broken splice
        # would either stack one row per update or eat the review's own rows and summary.
        waiting = _deep_done(resolution_planned=True)
        assert "| Resolve comments | ⏸ Waiting |  |" in waiting

        body = _splice_resolution_section(_splice_resolution_section(waiting, step), step)

        assert body.count("| Resolve comments |") == 1
        assert row in body
        assert f"Posted 3 findings: 1 Must fix, 2 Should fix.<!-- reviewhog:resolution:start -->{summary}" in body
        assert "| Publish | ✅ Done |" in body
        assert body.index("| Publish |") < body.index("| Resolve comments |")
        assert status_marker("rid") in body

    def test_splice_adds_the_row_to_a_review_that_planned_no_resolution(self) -> None:
        # A standalone resolution run on a reviewed PR finds a table without a Resolve row.
        body = _splice_resolution_section(
            _deep_done(), resolution_progress_step(done=0, total=2, fixed=0, left_for_you=0)
        )

        lines = body.split("\n")
        publish = next(i for i, line in enumerate(lines) if line.startswith("| Publish |"))
        assert lines[publish + 1] == "| Resolve comments | ⏳ 0/2 |  |"

    def test_final_step_buckets_outcomes_and_names_failures(self) -> None:
        # The closing tally is the PR author's durable record: already_fixed and obsolete collapse
        # into one bucket, and threads the run could not handle must be named, never silent.
        step = resolution_final_step(
            outcomes={"fixed": 2, "wont_fix": 1, "already_fixed": 1, "obsolete": 1, "escalate": 1},
            failed_turns=2,
        )
        assert step.status == "⚠️ 6/8"
        assert step.result == (
            "2 fixed with commits on your branch, 1 declined, 2 already settled, 1 left for you, couldn't handle 2"
        )
        assert step.summary == "Resolve pushed fixes for 2. 3 are left for you."


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
            self.team.id, str(report.id), resolution_progress_step(done=0, total=3, fixed=0, left_for_you=0)
        )

        assert _posts(mock_request) == ["/repos/o/r/issues/123/comments"]
        posted = next(c for c in mock_request.call_args_list if c.args[0] == "POST")
        assert "| Resolve comments | ⏳ 0/3 |  |" in posted.kwargs["json"]["body"]
        assert status_marker(str(report.id)) in posted.kwargs["json"]["body"]
        report.refresh_from_db()
        assert report.status_comment_id == 888

    def test_settle_only_update_never_creates_a_comment(
        self, mock_request: MagicMock, mock_paginated: MagicMock, mock_integration: MagicMock
    ) -> None:
        # A run with nothing to resolve settles a review's waiting row; on a PR without a status
        # comment it must not post a fresh comment that only says there was nothing to do.
        _wire_auth(mock_integration)
        mock_paginated.return_value = iter([])
        report = self._report()

        update_resolution_status_comment(
            self.team.id, str(report.id), RESOLUTION_NOTHING_TO_DO, create_if_missing=False
        )

        assert _posts(mock_request) == []
        report.refresh_from_db()
        assert report.status_comment_id is None

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
            self.team.id, str(report.id), resolution_progress_step(done=1, total=3, fixed=1, left_for_you=0)
        )

        assert _posts(mock_request) == []
        assert _patches(mock_request) == ["/repos/o/r/issues/comments/777"]
        patched = mock_request.call_args_list[1].kwargs["json"]["body"]
        assert "### reviewed" in patched
        assert "| Resolve comments | ⏳ 1/3 | 1 fixed with a commit on your branch |" in patched

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
            self.team.id, str(report.id), resolution_progress_step(done=1, total=3, fixed=1, left_for_you=0)
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
            resolution_progress_step(done=1, total=3, fixed=1, left_for_you=0),
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
