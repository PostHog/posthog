from collections.abc import Callable
from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding, ValidationVerdict
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH, REVIEW_MODE_FULL
from products.review_hog.backend.reviewer.fingerprint import ReviewHogMarker
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.models.perspective_selection import ChunkPerspectiveSelection
from products.review_hog.backend.reviewer.models.thread_resolution import CommitHold
from products.review_hog.backend.reviewer.persistence import persist_findings, persist_verdict, upsert_review_report
from products.review_hog.backend.reviewer.progress import SnapshotStats, TurnStats, run_outcome_markers
from products.review_hog.backend.reviewer.review_design import REVIEW_DESIGN_SINGLE_AGENT
from products.review_hog.backend.reviewer.status_comment import (
    FinalizeStatusCommentInput,
    _splice_resolution_row,
    ensure_status_comment,
    fail_status_comment,
    finalize_status_comment,
    maybe_refresh_status_comment,
    render_final_body,
    render_in_progress_body,
    render_resolution_final_row,
    render_resolution_held_row,
    render_resolution_progress_row,
    status_marker,
    update_resolution_status_comment,
)
from products.review_hog.backend.reviewer.tools.issue_deduplicator import AlreadyRaised
from products.review_hog.backend.temporal.activities import _fail_run

_MODULE = "products.review_hog.backend.reviewer.status_comment"
_REQUEST = f"{_MODULE}.github_api_request"
_PAGINATED = f"{_MODULE}.github_api_get_paginated"
_INTEGRATION = f"{_MODULE}.GitHubIntegration"


def _pair(n: int, priority: IssuePriority, *, is_valid: bool = True) -> tuple[ReviewIssueFinding, ValidationVerdict]:
    key = f"r1:a.py:{n}"
    finding = ReviewIssueFinding(
        issue_key=key, run_index=1, title="t", file="a.py", body="b", suggestion="s", priority=priority
    )
    return finding, ValidationVerdict(issue_key=key, is_valid=is_valid, argumentation="a")


_PAIRS = [
    _pair(1, IssuePriority.MUST_FIX),
    _pair(2, IssuePriority.CONSIDER),
    _pair(3, IssuePriority.SHOULD_FIX, is_valid=False),
]
_SELECTION = [ChunkPerspectiveSelection(chunk_id=1, perspectives=["a", "b", "c"], reason="r")]
_DEEP: dict[str, Any] = {
    "snapshot": SnapshotStats(files_reviewed=14),
    "turn": TurnStats(chunk_count=3, perspective_issue_count=14, blind_spot_issue_count=2, selection_chunks=_SELECTION),
    "head_sha": "b81c2e1ffff",
}
_STANDARD: dict[str, Any] = {"review_mode": REVIEW_MODE_FLASH, "review_design": REVIEW_DESIGN_SINGLE_AGENT}


def _running(stage: str | None, done: int | None = None, total: int | None = None, **kwargs: Any) -> str:
    progress = {"review_stage": stage, "done": done, "total": total} if stage else None
    return render_in_progress_body("rid", progress, **kwargs)


def _done(threshold: IssuePriority = IssuePriority.SHOULD_FIX, **kwargs: Any) -> str:
    return render_final_body("rid", threshold=threshold, review_url="https://g/review", **kwargs)


_BODY_CASES: list[tuple[str, Callable[[], str], list[str]]] = [
    (
        "deep_running",
        lambda: _running("reviewing", 7, 9, **_DEEP),
        [
            "### PostHog Review · Deep · reviewing `b81c2e1`",
            "| Prepare the diff | done | 14 files, 3 chunks |\n| Pick perspectives | done | 3 perspectives |",
            "| Run review passes | 7/9 |  |",
            "| Publish | waiting |  |",
        ],
    ),
    (
        "deep_failed",
        lambda: _running("validating", 1, 3, pairs=_PAIRS, failed=True, **_DEEP),
        [
            "### PostHog Review · Deep · couldn't finish reviewing `b81c2e1`",
            'The review failed at "Validate findings". Ask for a Deep review again to retry.',
            "| Merge overlapping findings | done | 16 → 3 |\n| Validate findings | failed |  |\n| Publish | skipped |  |",
        ],
    ),
    # The kickoff body has no progress, and a single-agent turn starts its sessions right after it.
    (
        "standard_kickoff",
        lambda: _running(None, **_STANDARD),
        ["Standard · reviewing this pull request", "| Main review and lenses | running |  |"],
    ),
    (
        "standard_failed",
        lambda: _running("single_agent_reviewing", failed=True, **_STANDARD),
        ["It runs again on the next push to this pull request.", "| Main review and lenses | failed |  |"],
    ),
    (
        "deep_done",
        lambda: _done(pairs=_PAIRS, report_url="https://ph.test/r", **_DEEP),
        [
            "### PostHog Review · Deep · reviewed `b81c2e1`\n\nPosted 1 finding: 1 Must fix.",
            "| Run review passes | done | 14 issues (+2 blind-spot) |",
            "| Validate findings | done | 2 kept, 1 dismissed |",
            # The full found count stays visible even when the threshold holds some findings back.
            '| Publish | done | 1 posted ([view review](https://g/review)) · 1 held back by the author\'s "Should fix" threshold ([view in PostHog](https://ph.test/r)) |',
        ],
    ),
    (
        "standard_done",
        lambda: _done(IssuePriority.CONSIDER, turn=TurnStats(perspective_issue_count=9), pairs=_PAIRS, **_STANDARD),
        [
            "Posted 2 findings: 1 Must fix, 1 Consider.",
            "| Main review and lenses | done | 9 issues |\n| Merge and cap | done | 9 → 2 |",
        ],
    ),
    ("standard_clean", lambda: _done(**_STANDARD), ["Nothing to post.", "| Publish | done | Nothing to post |"]),
]


class TestRenderBodies:
    @parameterized.expand(_BODY_CASES)
    def test_renders_the_step_table(self, _name: str, render: Callable[[], str], expected: list[str]) -> None:
        body = render()
        for fragment in expected:
            assert fragment in body, f"missing {fragment!r} in:\n{body}"
        assert status_marker("rid") in body  # the marker is what makes edit-in-place reuse possible
        assert all(ord(char) < 0x2600 for char in body), "the status comment carries no emoji"


class TestRenderFinalBody:
    @parameterized.expand(
        [
            # Whose settings gated the run must be named truthfully: blaming "the author's" settings
            # for a requester-gated run is the exact misattribution this wording exists to fix, and
            # the defensive default variant has no settings page to point at.
            ("author", 'the author\'s "Should fix" threshold'),
            ("override", 'the requester\'s "Should fix" threshold'),
            ("default", 'the default "Should fix" threshold'),
            # An unknown future value must degrade to the author wording, not crash the comment.
            ("mystery", 'the author\'s "Should fix" threshold'),
        ]
    )
    def test_held_back_sentence_attributes_the_gating_threshold(self, resolved_from: str, expected: str) -> None:
        body = render_final_body(
            "rid",
            pairs=[_pair(1, IssuePriority.CONSIDER), _pair(2, IssuePriority.CONSIDER)],
            threshold=IssuePriority.SHOULD_FIX,
            review_url=None,
            resolved_from=resolved_from,
            report_url="https://ph.test/project/1/code-review?review=rid",
            marker=ReviewHogMarker(version="reviewhog-flash-9-9", fingerprint="abc1234"),
        )
        assert f"2 held back by {expected}" in body, body
        # The version rides in a hidden HTML comment, so it adds no visible text to the PR.
        hidden = "<!-- reviewhog-version: reviewhog-flash-9-9 abc1234 -->"
        assert hidden in body
        assert "reviewhog-flash" not in body.replace(hidden, "")
        # Held-back findings are otherwise invisible to the author — the comment must not dead-end.
        assert "([view in PostHog](https://ph.test/project/1/code-review?review=rid))" in body

    @parameterized.expand(
        [
            ("default_on", REVIEW_MODE_FULL, True, True),
            ("author_opted_out", REVIEW_MODE_FULL, False, False),
            # A clean flash turn never celebrates, whatever the setting says.
            ("flash", REVIEW_MODE_FLASH, True, False),
        ]
    )
    @patch(f"{_MODULE}.random.choice", return_value=("https://example.test/dog.png", "A happy dog"))
    def test_clean_review_media_follows_the_preference(
        self, _name: str, review_mode: str, celebrate: bool, expect_media: bool, mock_choice: MagicMock
    ) -> None:
        body = render_final_body(
            "rid",
            threshold=IssuePriority.SHOULD_FIX,
            review_url=None,
            review_mode=review_mode,
            celebrate_clean_reviews=celebrate,
        )

        if expect_media:
            assert "![A happy dog](https://example.test/dog.png)" in body
            mock_choice.assert_called_once()
        else:
            assert "dog.png" not in body
            mock_choice.assert_not_called()

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
            pairs=[_pair(n, IssuePriority.MUST_FIX) for n in range(must_fix)],
            threshold=IssuePriority.SHOULD_FIX,
            review_url=None,
            review_mode=REVIEW_MODE_FLASH,
            capped_lens_parts=capped_lens_parts,
        )

        note = "This pull request is large, so the review ran in 4 parts with less depth than usual."
        assert (note in body) is expect_note

    @parameterized.expand([("clean_turn", 0, "Nothing to post."), ("turn_with_findings", 1, "Posted 1 finding")])
    def test_full_lists_what_other_comments_already_raise(self, _name: str, must_fix: int, opening: str) -> None:
        raised = [
            AlreadyRaised(title=f"Problem {n}", level="P2", comment_id=100 + n, commenter="greptile-apps[bot]")
            for n in range(12)
        ]

        body = render_final_body(
            "rid",
            pairs=[_pair(n, IssuePriority.MUST_FIX) for n in range(must_fix)],
            threshold=IssuePriority.SHOULD_FIX,
            review_url=None,
            raised_elsewhere=raised[:10],
            raised_elsewhere_count=len(raised),
            pr_url="https://github.com/o/r/pull/7",
        )

        # A Full turn that only repeated other reviewers must say so instead of celebrating a clean PR.
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
        assert mock_request.call_args.kwargs["json"]["body"].startswith("### PostHog Review · Standard · reviewing ")
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
        assert (
            '1 posted ([view review](https://g/review)) · 2 held back by the author\'s "Should fix" threshold' in body
        )
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

        fail_status_comment(self.team.id, report_id, review_mode=REVIEW_MODE_FLASH)

        assert _patches(mock_request) == ["/repos/o/r/issues/comments/555"]
        body = mock_request.call_args.kwargs["json"]["body"]
        # The entry point threads the turn's mode into the renderer; a dropped kwarg here would
        # leave a dead Standard run reading as a Deep one.
        assert body.startswith("### PostHog Review · Standard · couldn't finish reviewing ")


_DONE_BODY = f"### reviewed\n\n| Step | Status | Result |\n|---|---|---|\n| Publish | done | 1 posted |\n\n{status_marker('rid')}"
_OLD_BODY = (
    f"### reviewed\n\n{status_marker('rid')}\n\n"
    "<!-- reviewhog:resolution:start -->\n**Resolving comments: 0/3**\n<!-- reviewhog:resolution:end -->"
)


class TestResolutionRow:
    @parameterized.expand(
        [
            (
                "running",
                _DONE_BODY,
                [render_resolution_progress_row(done=2, total=5, fixed=1, left_for_you=0)],
                "| Publish | done | 1 posted |\n| Resolve comments | 2/5 | 1 fixed with a commit on your branch |",
            ),
            (
                # Every settled thread rewrites the row, so a broken splice would stack one row per update.
                "done_replaces_running",
                _DONE_BODY,
                [
                    render_resolution_progress_row(done=2, total=3, fixed=1, left_for_you=0),
                    render_resolution_final_row(outcomes={"fixed": 2, "escalate": 1}, failed_turns=0),
                ],
                "| Resolve comments | done | 2 fixed with commits on your branch, 1 left for you |",
            ),
            (
                "held",
                _DONE_BODY,
                [render_resolution_held_row(CommitHold.BRANCH_PROTECTED)],
                "| Resolve comments | skipped | Not run because this branch is protected |",
            ),
            (
                # A comment posted before the step table must not keep its stale resolution text.
                "old_marker_block",
                _OLD_BODY,
                [render_resolution_progress_row(done=1, total=3, fixed=0, left_for_you=0)],
                "| Step | Status | Result |\n|---|---|---|\n| Resolve comments | 1/3 |  |",
            ),
        ]
    )
    def test_splices_one_resolve_row_into_the_table(
        self, _name: str, body: str, rows: list[str], expected: str
    ) -> None:
        for row in rows:
            body = _splice_resolution_row(body, row)

        assert expected in body, body
        assert body.count("| Resolve comments |") == 1
        assert "### reviewed" in body
        assert status_marker("rid") in body
        assert "Resolving comments:" not in body

    def test_final_row_buckets_outcomes_and_names_failures(self) -> None:
        # The closing tally is the PR author's durable record: already_fixed and obsolete collapse
        # into one bucket, and threads the run could not handle must be named, never silent.
        row = render_resolution_final_row(
            outcomes={"fixed": 2, "wont_fix": 1, "already_fixed": 1, "obsolete": 1, "escalate": 1},
            failed_turns=2,
        )
        assert "2 fixed with commits on your branch, 1 declined, 2 already settled, 1 left for you" in row
        assert "couldn't handle 2" in row


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
            self.team.id, str(report.id), render_resolution_progress_row(done=0, total=3, fixed=0, left_for_you=0)
        )

        assert _posts(mock_request) == ["/repos/o/r/issues/123/comments"]
        posted = next(c for c in mock_request.call_args_list if c.args[0] == "POST")
        assert "| Resolve comments | 0/3 |  |" in posted.kwargs["json"]["body"]
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
            self.team.id, str(report.id), render_resolution_progress_row(done=1, total=3, fixed=1, left_for_you=0)
        )

        assert _posts(mock_request) == []
        assert _patches(mock_request) == ["/repos/o/r/issues/comments/777"]
        patched = mock_request.call_args_list[1].kwargs["json"]["body"]
        assert "### reviewed" in patched
        assert "| Resolve comments | 1/3 | 1 fixed with a commit on your branch |" in patched

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
            self.team.id, str(report.id), render_resolution_progress_row(done=1, total=3, fixed=1, left_for_you=0)
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
            render_resolution_progress_row(done=1, total=3, fixed=1, left_for_you=0),
            integration_row_id=42,
        )

        mock_integration.first_for_team_repository.assert_not_called()
        mock_integration_model.objects.get.assert_called_once_with(id=42, team_id=self.team.id)
        assert _patches(mock_request) == ["/repos/o/r/issues/comments/777"]


class TestFailRun(BaseTest):
    @parameterized.expand(
        [
            ("before_finalize", False, 1),
            # Finalize already bumped run_count, so the dying publish belongs to that same turn.
            ("in_publish_window", True, 1),
        ]
    )
    def test_returns_the_report_to_rest_and_records_the_failed_turn(
        self, _name: str, finalized: bool, expected_run_index: int
    ) -> None:
        # Publishing runs defer finalize's idle write to the publish stage, so the failure path must
        # restore rest itself or a dead run reads as in-progress in the UI until the staleness
        # cutoff. A report with no status comment (nothing to edit on GitHub) must still go idle.
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        report = ReviewReport.objects.for_team(self.team.id).get(id=report_id)
        assert report.status == ReviewReport.Status.ACTIVE
        report.head_sha = "a" * 40
        if finalized:
            report.run_count = 1
            report.completed_head_sha = report.head_sha
        report.save(update_fields=["head_sha", "run_count", "completed_head_sha"])

        _fail_run(self.team.id, report_id, review_mode="flash")

        report.refresh_from_db()
        assert report.status == ReviewReport.Status.IDLE
        markers = run_outcome_markers(self.team.id, [report_id])[report_id]
        assert [(m.outcome, m.reason, m.run_index, m.review_mode, m.head_sha) for m in markers] == [
            ("failed", "review_failed", expected_run_index, "flash", report.head_sha)
        ]
