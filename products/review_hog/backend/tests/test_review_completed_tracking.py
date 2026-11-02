import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.constants import (
    DEFAULT_REVIEW_ARM,
    FLASH_ARM,
    REVIEW_MODE_FLASH,
    REVIEW_MODE_FULL,
    REVIEW_MODEL,
    SINGLE_AGENT_ARM_SETS,
    SINGLE_AGENT_FLASH_ARM,
    VALIDATION_MODEL,
    VALIDATION_REASONING_EFFORT,
    SingleAgentArms,
)
from products.review_hog.backend.reviewer.finding_budget import budget_arm
from products.review_hog.backend.reviewer.fingerprint import ReviewHogMarker
from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRFileUpdate, PRMetadata
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.persistence import (
    finalize_review_report,
    persist_findings,
    persist_pr_snapshot,
    persist_verdicts,
    upsert_review_report,
)
from products.review_hog.backend.reviewer.push_gate import PushGateDecision
from products.review_hog.backend.reviewer.review_design import REVIEW_DESIGN_PIPELINE, REVIEW_DESIGN_SINGLE_AGENT
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError
from products.review_hog.backend.reviewer.tools.single_agent_review import FlashTurnStats
from products.review_hog.backend.temporal.activities import (
    FlashSessionStats,
    GatePushInput,
    TrackReviewCompletedInput,
    TrackReviewFailedInput,
    TrackReviewStartedInput,
    _gate_push,
    _notify_review_finished,
    _track_review_completed,
    _track_review_completed_safe,
    _track_review_failed,
    _track_review_started,
)
from products.review_hog.backend.temporal.types import TRIGGER_INBOX, TRIGGER_STAMPHOG
from products.signals.backend.enums import ReportPriority

_PR_URL = "https://github.com/o/r/pull/7"


def _pr_metadata(*, draft: bool = False) -> PRMetadata:
    return PRMetadata(
        number=7,
        title="t",
        state="open",
        draft=draft,
        created_at="",
        updated_at="",
        author="octocat",
        base_branch="main",
        head_branch="feat",
        head_sha="sha1",
        commits=3,
        additions=120,
        deletions=30,
        changed_files=7,
    )


def _issue(issue_id: str) -> Issue:
    return Issue(
        id=issue_id,
        title="t",
        file="a.py",
        lines=[LineRange(start=10)],
        issue="problem",
        suggestion="fix",
        priority=IssuePriority.MUST_FIX,
        source_perspective="Logic & Correctness",
    )


class TestTrackReviewCompleted(BaseTest):
    def _review_report(
        self,
        *,
        signal_report_id: str | None = None,
        trigger_source: str | None = None,
        signal_priority: ReportPriority | None = None,
    ) -> str:
        return upsert_review_report(
            team_id=self.team.id,
            repository="o/r",
            pr_url=_PR_URL,
            pr_metadata=_pr_metadata(),
            signal_report_id=signal_report_id,
            trigger_source=trigger_source,
            signal_priority=signal_priority,
        )

    def _tracking_input(
        self,
        report_id: str,
        *,
        published: bool = True,
        turn_trigger_source: str = "manual",
        review_mode: str = REVIEW_MODE_FULL,
        flash_reasoning_effort: str = "medium",
        marker: ReviewHogMarker | None = None,
        flash_turn: FlashTurnStats | None = None,
        flash_sessions: FlashSessionStats | None = None,
        review_design: str = REVIEW_DESIGN_PIPELINE,
        arm_set: str = "control",
    ) -> TrackReviewCompletedInput:
        return TrackReviewCompletedInput(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="sha1",
            run_index=1,
            published=published,
            workflow_started_at=(datetime.now(UTC) - timedelta(seconds=90)).isoformat(),
            turn_trigger_source=turn_trigger_source,
            review_mode=review_mode,
            flash_reasoning_effort=flash_reasoning_effort,
            marker=marker,
            flash_turn=flash_turn,
            flash_sessions=flash_sessions,
            review_design=review_design,
            arm_set=arm_set,
        )

    @parameterized.expand([(True,), (False,)])
    def test_captures_the_turn_with_review_scoped_properties(self, published: bool) -> None:
        # Dashboards count reviews from this event's name and these exact properties — a rename,
        # a dropped property, or a broken finding count silently zeroes them.
        report_id = self._review_report()
        persist_pr_snapshot(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="sha1",
            # The report row says not a draft, so the draft property must come from the turn's snapshot.
            pr_metadata=_pr_metadata(draft=True),
            pr_comments=[],
            # One reviewable file: raw PR additions (120) vs reviewable additions (80) must diverge
            # so the assertions below can't pass with the two properties swapped.
            pr_files=[PRFile(filename="a.py", status="modified", additions=80, deletions=10)],
        )
        issues = [_issue("1-1-1"), _issue("1-1-2")]
        persist_findings(team_id=self.team.id, report_id=report_id, issues=issues, run_index=1)
        persist_verdicts(
            team_id=self.team.id,
            report_id=report_id,
            issues=issues,
            run_index=1,
            validations={
                # The validator downgrades the must_fix finding: the severity-mix props must count
                # the override (effective_priority), not the reviewer's original call.
                "1-1-1": IssueValidation(
                    is_valid=True, argumentation="real", category="bug", adjusted_priority=IssuePriority.SHOULD_FIX
                ),
                "1-1-2": IssueValidation(is_valid=False, argumentation="not real", category="bug"),
            },
        )

        with patch("products.review_hog.backend.temporal.activities.posthoganalytics.capture") as capture:
            _track_review_completed(
                self._tracking_input(
                    report_id,
                    published=published,
                    marker=ReviewHogMarker(version="reviewhog-full-9-9", fingerprint="abc1234"),
                )
            )

        capture.assert_called_once()
        kwargs = capture.call_args.kwargs
        assert kwargs["event"] == "reviewhog_review_completed"
        # No acting user resolved on this report — attribution falls back to the team.
        assert kwargs["distinct_id"] == str(self.team.uuid)
        props = kwargs["properties"]
        assert props["repository"] == "o/r"
        assert props["pr_number"] == 7
        assert props["run_index"] == 1
        assert props["trigger_source"] == "manual"
        assert props["turn_trigger_source"] == "manual"
        assert props["author_login"] == "octocat"
        assert props["published"] is published
        assert props["findings_total"] == 2
        assert props["findings_valid"] == 1
        assert props["findings_must_fix"] == 0  # downgraded by the validator's adjusted_priority
        assert props["findings_should_fix"] == 1
        assert props["findings_consider"] == 0
        assert props["review_mode"] == "full"
        assert props["review_model"] == REVIEW_MODEL
        assert props["review_runtime_adapter"] == DEFAULT_REVIEW_ARM.runtime_adapter.value
        assert props["review_reasoning_effort"] == DEFAULT_REVIEW_ARM.reasoning_effort.value
        assert props["review_arm_fallback"] is False
        assert props["review_tier"] == "human"
        assert props["signal_priority"] is None
        assert props["signal_report_id"] is None
        assert props["pr_additions"] == 120
        assert props["pr_deletions"] == 30
        assert props["pr_changed_files"] == 7
        assert props["pr_commits"] == 3
        assert props["pr_reviewable_additions"] == 80
        assert props["pr_draft"] is True
        # The finding budget's effect is measured by splitting on this, so it must be on every turn.
        assert props["finding_budget_arm"] == budget_arm("o/r", 7)
        assert props["review_round"] == 1
        assert 90 <= props["duration_seconds"] < 600
        assert props["reviewhog_version"] == "reviewhog-full-9-9"
        assert props["reviewhog_fingerprint"] == "abc1234"

        hooks = (MagicMock(side_effect=RuntimeError("callback down")), MagicMock())
        with patch("products.review_hog.backend.temporal.activities.get_finished_review_hooks", return_value=hooks):
            _notify_review_finished(
                team_id=self.team.id,
                report_id=report_id,
                run_index=1,
                review_mode="full",
                failed=False,
                published=published,
            )
        finished = hooks[1].call_args.args[0]
        assert (finished.repository, finished.pr_number, finished.findings_count) == ("o/r", 7, 1)
        assert (finished.failed, finished.published) == (False, published)
        assert finished.review_url.endswith(f"/project/{self.team.id}/code-review?review={report_id}")

    def test_single_agent_turn_reports_its_finding_funnel_and_sessions(self) -> None:
        # The cap, the dedup calls, and the lens sessions are only measurable through these
        # properties, the must-fix share is how priority inflation shows up before the must-fix
        # ceiling starts cutting, and a dedup fallback marks a turn whose drops were positional only.
        report_id = self._review_report()
        turn = FlashTurnStats(
            cap=6,
            lens_part_count=2,
            reviewable_lines=900,
            candidates={"main": 4, "performance_reliability": 0, "contracts_security": 3},
            must_fix={"main": 1, "performance_reliability": 0, "contracts_security": 3},
            after_dedup=5,
            dropped={"dedup_anchor": 2, "cap": 1},
            kept=4,
            dedup_fell_back=True,
            budget_left=3,
            changed_lines=40,
            must_fix_on_change=1,
            must_fix_off_change=2,
        )
        sessions = FlashSessionStats(lens_failures=1, lens_timeouts=1, slowest_session_seconds=412.5, arm_fallbacks=2)
        trial = SingleAgentArms(main=replace(SINGLE_AGENT_FLASH_ARM, model="gpt-6-luna"), lens=SINGLE_AGENT_FLASH_ARM)

        with (
            patch("products.review_hog.backend.temporal.activities.posthoganalytics.capture") as capture,
            patch.dict(SINGLE_AGENT_ARM_SETS, {"trial": trial}),
        ):
            _track_review_completed(
                self._tracking_input(
                    report_id,
                    review_mode=REVIEW_MODE_FLASH,
                    review_design=REVIEW_DESIGN_SINGLE_AGENT,
                    flash_turn=turn,
                    flash_sessions=sessions,
                    arm_set="trial",
                )
            )
            _track_review_completed(self._tracking_input(report_id))

        single_agent, pipeline = (call.kwargs["properties"] for call in capture.call_args_list)
        assert {key: value for key, value in single_agent.items() if key.startswith("flash_")} == {
            "flash_cap": 6,
            "flash_lens_parts": 2,
            "flash_reviewable_lines": 900,
            "flash_candidates": {"main": 4, "performance_reliability": 0, "contracts_security": 3},
            "flash_must_fix": {"main": 1, "performance_reliability": 0, "contracts_security": 3},
            "flash_must_fix_share": {"main": 0.25, "performance_reliability": None, "contracts_security": 1.0},
            "flash_after_dedup": 5,
            "flash_dropped": {"dedup_anchor": 2, "cap": 1},
            "flash_kept": 4,
            "flash_dedup_fallback": True,
            "flash_budget_left": 3,
            "flash_changed_lines": 40,
            "flash_must_fix_on_change": 1,
            "flash_must_fix_off_change": 2,
            "flash_lens_failures": 1,
            "flash_lens_timeouts": 1,
            "flash_slowest_session_seconds": 412.5,
            "flash_coordinator": False,
            "flash_arm_fallbacks": 2,
        }
        assert not [key for key in pipeline if key.startswith("flash_")]
        assert (single_agent["single_agent_arm_set"], single_agent["review_model"]) == ("trial", "gpt-6-luna")
        assert pipeline["single_agent_arm_set"] == "control"

    def test_missing_snapshot_still_captures_without_pr_size(self) -> None:
        # A turn whose pr_snapshot is unavailable must still count as a review — size props go
        # null rather than the capture (and with it the review count) being lost.
        report_id = self._review_report()

        with patch("products.review_hog.backend.temporal.activities.posthoganalytics.capture") as capture:
            _track_review_completed(self._tracking_input(report_id, published=False))

        capture.assert_called_once()
        props = capture.call_args.kwargs["properties"]
        assert props["pr_additions"] is None
        assert props["pr_reviewable_additions"] is None
        # Unknown is not "not a draft": a False here would count the turn as a ready PR.
        assert props["pr_draft"] is None
        assert props["findings_total"] == 0
        # A turn without a marker ran on an unknown release; the current deploy's version would mislabel it.
        assert props["reviewhog_version"] is None
        assert props["reviewhog_fingerprint"] is None

    @parameterized.expand([("completed",), ("failed",), ("started",)])
    def test_event_uuid_is_stable_across_retries_and_separate_for_each_mode_and_design(self, event: str) -> None:
        # A failed turn keeps its run index, so a Flash turn on the other design can reuse it. A shared
        # id there makes PostHog drop the second turn's event.
        report_id = self._review_report()
        emit = {
            "completed": lambda mode, design: _track_review_completed(
                self._tracking_input(report_id, review_mode=mode, review_design=design)
            ),
            "failed": lambda mode, design: _track_review_failed(
                TrackReviewFailedInput(
                    team_id=self.team.id,
                    report_id=report_id,
                    run_index=1,
                    turn_trigger_source="manual",
                    review_mode=mode,
                    review_design=design,
                )
            ),
            "started": lambda mode, design: _track_review_started(
                TrackReviewStartedInput(
                    team_id=self.team.id,
                    report_id=report_id,
                    head_sha="sha1",
                    run_index=1,
                    turn_trigger_source="manual",
                    review_mode=mode,
                    review_design=design,
                )
            ),
        }[event]

        with patch("products.review_hog.backend.temporal.activities.posthoganalytics.capture") as capture:
            emit(REVIEW_MODE_FULL, REVIEW_DESIGN_PIPELINE)
            emit(REVIEW_MODE_FULL, REVIEW_DESIGN_PIPELINE)
            emit(REVIEW_MODE_FLASH, REVIEW_DESIGN_PIPELINE)
            emit(REVIEW_MODE_FLASH, REVIEW_DESIGN_PIPELINE)
            emit(REVIEW_MODE_FLASH, REVIEW_DESIGN_SINGLE_AGENT)

        full, full_retry, flash, flash_retry, single_agent = capture.call_args_list
        assert full.kwargs["uuid"] == str(uuid.uuid5(uuid.NAMESPACE_URL, f"reviewhog_review_{event}:{report_id}:1"))
        assert flash.kwargs["uuid"] == str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"reviewhog_review_{event}:{report_id}:1:flash")
        )
        assert full.kwargs["uuid"] == full_retry.kwargs["uuid"]
        assert flash.kwargs["uuid"] == flash_retry.kwargs["uuid"]
        assert len({full.kwargs["uuid"], flash.kwargs["uuid"], single_agent.kwargs["uuid"]}) == 3

    def test_a_skipped_push_rests_the_report_and_counts_once_per_head(self) -> None:
        # A skipped turn ends before any stage that returns the report to rest, and a skipped turn
        # keeps the next turn's run_index, so a run_index-keyed event would merge two skipped pushes.
        report_id = self._review_report()
        for head_sha, draft in (("sha1", True), ("sha2", False)):
            persist_pr_snapshot(
                team_id=self.team.id,
                report_id=report_id,
                head_sha=head_sha,
                pr_metadata=_pr_metadata(draft=draft),
                pr_comments=[],
                pr_files=[],
            )
        decision = PushGateDecision(
            skip=True,
            would_skip=True,
            reason="system_one_below_threshold",
            probability=0.03,
            model="jevk5",
            own_commits=2,
            own_code_lines=14,
        )

        with (
            patch("products.review_hog.backend.temporal.activities._installation_auth", return_value=("tok", None)),
            patch("products.review_hog.backend.temporal.activities.PushGate") as gate,
            patch("products.review_hog.backend.temporal.activities.posthoganalytics.capture") as capture,
        ):
            gate.return_value.decide.return_value = decision
            gate.return_value.record_small_change_streak.side_effect = lambda decision, **_: decision
            results = [
                _gate_push(
                    GatePushInput(
                        team_id=self.team.id,
                        report_id=report_id,
                        repository="o/r",
                        previous_head_sha="sha0",
                        head_sha=head_sha,
                        run_index=2,
                        review_mode=REVIEW_MODE_FLASH,
                    )
                )
                for head_sha in ("sha1", "sha2")
            ]

        assert ReviewReport.objects.for_team(self.team.id).get(id=report_id).status == ReviewReport.Status.IDLE
        assert [(result.skip, result.reason) for result in results] == [(True, "system_one_below_threshold")] * 2
        recorded = gate.return_value.record_small_change_streak.call_args_list
        assert [call.args[0] for call in recorded] == results
        first, second = capture.call_args_list
        assert first.kwargs["event"] == "reviewhog_push_gate_decided"
        props = first.kwargs["properties"]
        assert (props["skipped"], props["reason"], props["system_one_probability"], props["own_code_lines"]) == (
            True,
            "system_one_below_threshold",
            0.03,
            14,
        )
        assert first.kwargs["uuid"] != second.kwargs["uuid"]
        # Each push reports the draft state of its own head, and only a ready PR gets a next push chance.
        assert (props["pr_draft"], second.kwargs["properties"]["pr_draft"]) == (True, False)
        assert (props["next_push_probability"], second.kwargs["properties"]["next_push_probability"]) == (None, 0.559)

    @parameterized.expand(
        [
            ("quiet_previous_review", False, False, (True, "quiet_small_push", 0, 400)),
            ("previous_review_found_a_bug", True, False, (False, "system_one_above_threshold", 1, 400)),
            # A retry after a failed publish runs one run_index higher at the head its first attempt finalized.
            ("retry_of_a_finalized_head", False, True, (False, "system_one_above_threshold", None, None)),
        ]
    )
    def test_the_gate_reads_the_previous_turns_findings_and_the_pr_size(
        self,
        _name: str,
        previous_finding: bool,
        head_finalized: bool,
        expected: tuple[bool, str, int | None, int | None],
    ) -> None:
        report_id = self._review_report()
        persist_pr_snapshot(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="sha1",
            pr_metadata=_pr_metadata(),
            pr_comments=[],
            pr_files=[
                PRFile(filename="a.py", status="modified", additions=300, deletions=100),
                PRFile(filename="pnpm-lock.yaml", status="modified", additions=900, deletions=0),
            ],
        )
        if previous_finding:
            issues = [_issue("1-1-1")]
            persist_findings(team_id=self.team.id, report_id=report_id, issues=issues, run_index=1)
            persist_verdicts(
                team_id=self.team.id,
                report_id=report_id,
                issues=issues,
                run_index=1,
                validations={"1-1-1": IssueValidation(is_valid=True, argumentation="real")},
            )
        if head_finalized:
            finalize_review_report(
                team_id=self.team.id, report_id=report_id, body_markdown="# r", run_index=1, head_sha="sha1"
            )
        decision = PushGateDecision(
            skip=False, would_skip=False, reason="system_one_above_threshold", probability=0.8, own_code_lines=12
        )

        with (
            patch("products.review_hog.backend.temporal.activities._installation_auth", return_value=("tok", None)),
            patch("products.review_hog.backend.temporal.activities.PushGate") as gate,
            patch("products.review_hog.backend.temporal.activities.apply_throttle", side_effect=lambda d, **_: d),
            patch("products.review_hog.backend.temporal.activities.posthoganalytics.capture") as capture,
        ):
            gate.return_value.decide.return_value = decision
            gate.return_value.record_small_change_streak.side_effect = lambda decision, **_: decision
            result = _gate_push(
                GatePushInput(
                    team_id=self.team.id,
                    report_id=report_id,
                    repository="o/r",
                    previous_head_sha="sha0",
                    head_sha="sha1",
                    run_index=2,
                    review_mode=REVIEW_MODE_FLASH,
                )
            )

        props = capture.call_args.kwargs["properties"]
        assert (result.skip, result.reason, props["previous_findings"], props["reviewable_lines"]) == expected

    @parameterized.expand(
        [
            ("unchanged_in_the_treatment_arm", "limit = 10", [], True, (True, "zero_change", 0, False)),
            ("unchanged_in_the_control_arm", "limit = 10", [], False, (False, "zero_change", 0, False)),
            # The snapshot leaves a lockfile out, so its change is unseen, and it changes what the code runs with.
            (
                "lockfile_in_the_pr",
                "limit = 10",
                ["pnpm-lock.yaml"],
                True,
                (False, "system_one_above_threshold", 0, False),
            ),
            ("small_code_change", "limit = 20", [], True, (False, "system_one_above_threshold", 2, True)),
            (
                "small_code_change_with_a_lockfile_in_the_pr",
                "limit = 20",
                ["pnpm-lock.yaml"],
                True,
                (False, "system_one_above_threshold", 2, False),
            ),
        ]
    )
    def test_the_gate_compares_the_stored_pr_diff_of_both_heads(
        self,
        _name: str,
        changed_code: str,
        skipped_paths: list[str],
        treatment: bool,
        expected: tuple[bool, str, int, bool],
    ) -> None:
        report_id = self._review_report()

        def code_file(code: str) -> PRFile:
            return PRFile(
                filename="a.py",
                status="modified",
                additions=900,
                deletions=0,
                changes=[
                    PRFileUpdate(type="addition", new_start_line=1, new_end_line=1, code=code),
                    PRFileUpdate(
                        type="addition",
                        new_start_line=2,
                        new_end_line=900,
                        code="\n".join(f"x{line} = {line}" for line in range(2, 901)),
                    ),
                ],
            )

        for head_sha, code in (("sha0", "limit = 10"), ("sha1", changed_code)):
            persist_pr_snapshot(
                team_id=self.team.id,
                report_id=report_id,
                head_sha=head_sha,
                pr_metadata=_pr_metadata(),
                pr_comments=[],
                pr_files=[code_file(code)],
                review_design=REVIEW_DESIGN_SINGLE_AGENT,
                skipped_paths=skipped_paths,
            )
        decision = PushGateDecision(
            skip=False, would_skip=False, reason="system_one_above_threshold", own_code_lines=100
        )

        with (
            patch("products.review_hog.backend.temporal.activities._installation_auth", return_value=("tok", None)),
            patch("products.review_hog.backend.temporal.activities.PushGate") as gate,
            patch("products.review_hog.backend.temporal.activities.apply_throttle", side_effect=lambda d, **_: d),
            patch("products.review_hog.backend.temporal.activities.posthoganalytics.capture") as capture,
        ):
            gate.return_value.decide.return_value = decision
            gate.return_value.record_small_change_streak.side_effect = lambda decision, **_: decision
            result = _gate_push(
                GatePushInput(
                    team_id=self.team.id,
                    report_id=report_id,
                    repository="o/r",
                    previous_head_sha="sha0",
                    head_sha="sha1",
                    run_index=3,
                    review_mode=REVIEW_MODE_FLASH,
                    zero_change_skip=treatment,
                    delta_band=treatment,
                    coordinator=not treatment,
                )
            )

        props = capture.call_args.kwargs["properties"]
        assert (result.skip, result.reason, props["pr_changed_lines"], result.delta_review) == expected
        assert (props["zero_change_skip_arm"], props["delta_band_arm"], props["coordinator"]) == (
            treatment,
            treatment,
            not treatment,
        )

    def _gate_draft_push(self, report_id: str, live_pr: dict[str, object] | Exception) -> tuple[PushGateDecision, Any]:
        live = MagicMock(side_effect=live_pr) if isinstance(live_pr, Exception) else MagicMock()
        live.return_value.json.return_value = live_pr
        with (
            patch("products.review_hog.backend.temporal.activities._installation_auth", return_value=("tok", None)),
            patch(
                "products.review_hog.backend.reviewer.push_gate.github_api_request",
                side_effect=GitHubAPIError("gone", status=404),
            ),
            patch("products.review_hog.backend.temporal.activities.github_api_request", live),
            patch("products.review_hog.backend.temporal.activities.posthoganalytics.capture") as capture,
        ):
            decision = _gate_push(
                GatePushInput(
                    team_id=self.team.id,
                    report_id=report_id,
                    repository="o/r",
                    previous_head_sha="sha0",
                    head_sha="sha1",
                    run_index=2,
                    review_mode=REVIEW_MODE_FLASH,
                )
            )
        return decision, capture

    @parameterized.expand(
        [
            ("still_a_draft", [True], {"draft": True}, True, "draft"),
            # The author marks the PR ready without a push: the ready turn re-fetches the same head.
            ("marked_ready_at_the_same_head", [True, False], {"draft": True}, False, "compare_unavailable"),
            # The queue drops a ready request for the head a running turn gates, so the gate reads GitHub again.
            ("marked_ready_while_the_turn_runs", [True], {"draft": False}, False, "compare_unavailable"),
            ("live_read_fails", [True], GitHubAPIError("boom", status=502), False, "compare_unavailable"),
            (
                "live_read_rate_limited",
                [True],
                GitHubRateLimitError("limited", retry_after=60),
                False,
                "compare_unavailable",
            ),
            ("live_read_over_budget", [True], GitHubEgressBudgetExhausted("shed"), False, "compare_unavailable"),
        ]
    )
    def test_the_gate_reads_the_draft_state_of_the_latest_fetch(
        self,
        _name: str,
        fetched_drafts: list[bool],
        live_pr: dict[str, object] | Exception,
        skip: bool,
        reason: str,
    ) -> None:
        report_id = self._review_report()
        for draft in fetched_drafts:
            persist_pr_snapshot(
                team_id=self.team.id,
                report_id=report_id,
                head_sha="sha1",
                pr_metadata=_pr_metadata(draft=draft),
                pr_comments=[],
                pr_files=[],
            )

        decision, _capture = self._gate_draft_push(report_id, live_pr)

        assert (decision.skip, decision.reason) == (skip, reason)

    def test_a_draft_skip_and_the_ready_decision_at_one_head_stay_two_events(self) -> None:
        report_id = self._review_report()
        persist_pr_snapshot(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="sha1",
            pr_metadata=_pr_metadata(draft=True),
            pr_comments=[],
            pr_files=[],
        )

        _skip, draft_capture = self._gate_draft_push(report_id, {"draft": True})
        _review, ready_capture = self._gate_draft_push(report_id, {"draft": False})

        draft_event, ready_event = draft_capture.call_args.kwargs, ready_capture.call_args.kwargs
        assert draft_event["uuid"] != ready_event["uuid"]
        assert (draft_event["properties"]["pr_draft"], ready_event["properties"]["pr_draft"]) == (True, False)

    def test_capture_failure_is_swallowed(self) -> None:
        # Telemetry must never fail a review — losing this guard would fail review turns on any
        # analytics outage.
        report_id = self._review_report()

        with patch(
            "products.review_hog.backend.temporal.activities.posthoganalytics.capture",
            side_effect=RuntimeError("analytics down"),
        ):
            _track_review_completed_safe(self._tracking_input(report_id))

    def test_events_report_the_reports_persisted_arm(self) -> None:
        # The experiment's per-arm split reads review_model off both events; an event that falls
        # back to the module pins while the report ran its persisted Codex arm mislabels every
        # Sol review as Sonnet and the whole comparison dissolves.
        report_id = self._review_report()
        ReviewReport.objects.for_team(self.team.id).filter(id=report_id).update(
            review_runtime_adapter="codex",
            review_model="gpt-5.6-sol",
            review_reasoning_effort="xhigh",
            review_initial_permission_mode="full-access",
        )

        with patch("products.review_hog.backend.temporal.activities.posthoganalytics.capture") as capture:
            _track_review_completed(self._tracking_input(report_id))
            _track_review_failed(TrackReviewFailedInput(team_id=self.team.id, report_id=report_id, run_index=1))

        completed, failed = capture.call_args_list
        for call in (completed, failed):
            props = call.kwargs["properties"]
            assert props["review_model"] == "gpt-5.6-sol"
            assert props["review_runtime_adapter"] == "codex"
            assert props["review_reasoning_effort"] == "xhigh"
            assert props["review_arm_fallback"] is False
        assert failed.kwargs["event"] == "reviewhog_review_failed"
        assert failed.kwargs["properties"]["run_index"] == 1
        # The failed event needs its own stable uuid namespace: colliding with the completed event's
        # would make ingestion dedupe a real failure against a later success of the same turn.
        assert failed.kwargs["uuid"] != completed.kwargs["uuid"]

    def test_every_turn_event_names_the_arms_of_each_split(self) -> None:
        # Failure and start rates per arm need the arms on the failed and started events too, because a failed
        # turn has no completed event to join against.
        report_id = self._review_report()

        with patch("products.review_hog.backend.temporal.activities.posthoganalytics.capture") as capture:
            _track_review_started(
                TrackReviewStartedInput(
                    team_id=self.team.id,
                    report_id=report_id,
                    run_index=1,
                    head_sha="sha1",
                    turn_trigger_source=None,
                    arm_set="trial",
                    zero_change_skip_arm=True,
                    delta_band_arm=True,
                )
            )
            _track_review_failed(
                TrackReviewFailedInput(
                    team_id=self.team.id,
                    report_id=report_id,
                    run_index=1,
                    arm_set="trial",
                    zero_change_skip_arm=True,
                    delta_band_arm=True,
                )
            )
            _track_review_completed(
                replace(
                    self._tracking_input(report_id), arm_set="trial", zero_change_skip_arm=True, delta_band_arm=True
                )
            )

        for call in capture.call_args_list:
            props = call.kwargs["properties"]
            assert (props["single_agent_arm_set"], props["zero_change_skip_arm"], props["delta_band_arm"]) == (
                "trial",
                True,
                True,
            )

    def test_events_carry_the_tier_and_report_link_of_an_agent_pr(self) -> None:
        # The per-tier dashboards split on these: an event that drops the tier, the priority, or
        # the report link makes a cheap agent review indistinguishable from a full one, and the
        # turn's own trigger is what tells a person's re-trigger of an inbox report apart from
        # the report's first turn. The started event is the third event of a turn: a dashboard
        # compares it against completed to see a lift, so it must carry the same labels.
        signal_report_id = str(uuid.uuid4())
        report_id = self._review_report(
            signal_report_id=signal_report_id, trigger_source=TRIGGER_INBOX, signal_priority=ReportPriority.P3
        )

        with patch("products.review_hog.backend.temporal.activities.posthoganalytics.capture") as capture:
            _track_review_completed(self._tracking_input(report_id, turn_trigger_source=TRIGGER_STAMPHOG))
            _track_review_failed(
                TrackReviewFailedInput(
                    team_id=self.team.id, report_id=report_id, run_index=1, turn_trigger_source=TRIGGER_INBOX
                )
            )
            _track_review_started(
                TrackReviewStartedInput(
                    team_id=self.team.id,
                    report_id=report_id,
                    head_sha="sha1",
                    run_index=1,
                    turn_trigger_source=TRIGGER_INBOX,
                )
            )

        completed, failed, started = capture.call_args_list
        assert started.kwargs["event"] == "reviewhog_review_started"
        expected_validator_effort = VALIDATION_REASONING_EFFORT.value if VALIDATION_REASONING_EFFORT else None
        for call in (completed, failed, started):
            props = call.kwargs["properties"]
            assert props["review_tier"] == "agent_p3_p4"
            assert props["signal_priority"] == "P3"
            assert props["signal_report_id"] == signal_report_id
            assert props["trigger_source"] == "inbox"
            assert props["review_model"] == "gpt-6.1-sol"
            assert props["review_reasoning_effort"] == "low"
            assert props["review_arm_fallback"] is False
            # The validator and resolver are fixed pins, but the event is where a cost dashboard
            # reads them, so every event names them next to the reviewer arm.
            assert props["validator_model"] == VALIDATION_MODEL
            assert props["validator_reasoning_effort"] == expected_validator_effort
        assert completed.kwargs["properties"]["turn_trigger_source"] == "stamphog"
        assert failed.kwargs["properties"]["turn_trigger_source"] == "inbox"
        assert started.kwargs["properties"]["turn_trigger_source"] == "inbox"
        # No snapshot for this head, so the draft state is unknown on both events that carry it.
        assert completed.kwargs["properties"]["pr_draft"] is None
        assert started.kwargs["properties"]["pr_draft"] is None
        # Three events per turn, three uuid namespaces: a shared one would dedupe a start or a
        # failure against the completion of the same turn.
        assert len({call.kwargs["uuid"] for call in (completed, failed, started)}) == 3

    @parameterized.expand(
        [
            ("medium", REVIEW_MODEL, "medium"),
            ("xhigh", REVIEW_MODEL, "xhigh"),
            ("stale_model", "gpt-9-vanished", "xhigh"),
        ]
    )
    def test_flash_turn_events_name_the_flash_arm_in_both_seats(self, _name: str, model: str, effort: str) -> None:
        # The cost comparison splits on review_mode and reads the reviewer and validator models off
        # the same events; a flash turn reporting the stored Sol/Opus pins would price every flash
        # review as a full one and contaminate the per-arm dashboards.
        report_id = self._review_report()
        ReviewReport.objects.for_team(self.team.id).filter(id=report_id).update(review_model=model)

        with patch("products.review_hog.backend.temporal.activities.posthoganalytics.capture") as capture:
            _track_review_completed(
                self._tracking_input(report_id, review_mode=REVIEW_MODE_FLASH, flash_reasoning_effort=effort)
            )
            _track_review_failed(
                TrackReviewFailedInput(
                    team_id=self.team.id,
                    report_id=report_id,
                    run_index=1,
                    review_mode=REVIEW_MODE_FLASH,
                    flash_reasoning_effort=effort,
                )
            )
            _track_review_started(
                TrackReviewStartedInput(
                    team_id=self.team.id,
                    report_id=report_id,
                    head_sha="sha1",
                    run_index=1,
                    turn_trigger_source="ui",
                    review_mode=REVIEW_MODE_FLASH,
                    flash_reasoning_effort=effort,
                )
            )

        for call in capture.call_args_list:
            props = call.kwargs["properties"]
            assert props["review_mode"] == "flash"
            assert props["review_model"] == FLASH_ARM.model
            assert props["review_reasoning_effort"] == effort
            assert props["validator_model"] == FLASH_ARM.model
            assert props["validator_reasoning_effort"] == effort
            assert props["review_arm_fallback"] is False
            # The tier stays the report's: flash is a per-turn switch, not a tier.
            assert props["review_tier"] == "human"

    @parameterized.expand(
        [
            ("stale_model", "codex", "gpt-9-vanished", "high", "full-access"),
            # The model string matches the default pins, so a model-only comparison would miss the
            # failed assignment; only the full-bundle comparison flags it.
            ("default_model_unknown_adapter", "warp", REVIEW_MODEL, "xhigh", None),
        ]
    )
    def test_stale_arm_events_flag_the_fallback(
        self, _name: str, adapter: str, model: str, effort: str, permission_mode: str | None
    ) -> None:
        # A persisted assignment that fails resolution runs the default pins; the event must both
        # say what ran AND flag the deviation, or contaminated turns are indistinguishable from
        # genuine default-arm turns in the per-arm dashboards.
        report_id = self._review_report()
        ReviewReport.objects.for_team(self.team.id).filter(id=report_id).update(
            review_runtime_adapter=adapter,
            review_model=model,
            review_reasoning_effort=effort,
            review_initial_permission_mode=permission_mode,
        )

        with patch("products.review_hog.backend.temporal.activities.posthoganalytics.capture") as capture:
            _track_review_completed(self._tracking_input(report_id))

        props = capture.call_args.kwargs["properties"]
        assert props["review_model"] == REVIEW_MODEL
        assert props["review_arm_fallback"] is True
