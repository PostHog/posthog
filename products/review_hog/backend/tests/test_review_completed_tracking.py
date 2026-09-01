from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.constants import DEFAULT_REVIEW_ARM, REVIEW_MODEL
from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.persistence import (
    persist_findings,
    persist_pr_snapshot,
    persist_verdicts,
    upsert_review_report,
)
from products.review_hog.backend.temporal.activities import (
    TrackReviewCompletedInput,
    TrackReviewFailedInput,
    _track_review_completed,
    _track_review_completed_safe,
    _track_review_failed,
)

_PR_URL = "https://github.com/o/r/pull/7"


def _pr_metadata() -> PRMetadata:
    return PRMetadata(
        number=7,
        title="t",
        state="open",
        draft=False,
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
    def _review_report(self) -> str:
        # The upsert draws a random experiment arm; pin it so arm-property assertions are deterministic.
        with patch("products.review_hog.backend.reviewer.persistence.draw_review_arm", return_value=DEFAULT_REVIEW_ARM):
            return upsert_review_report(
                team_id=self.team.id, repository="o/r", pr_url=_PR_URL, pr_metadata=_pr_metadata()
            )

    def _tracking_input(self, report_id: str, *, published: bool = True) -> TrackReviewCompletedInput:
        return TrackReviewCompletedInput(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="sha1",
            run_index=1,
            published=published,
            workflow_started_at=(datetime.now(UTC) - timedelta(seconds=90)).isoformat(),
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
            pr_metadata=_pr_metadata(),
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
            _track_review_completed(self._tracking_input(report_id, published=published))

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
        assert props["author_login"] == "octocat"
        assert props["published"] is published
        assert props["findings_total"] == 2
        assert props["findings_valid"] == 1
        assert props["findings_must_fix"] == 0  # downgraded by the validator's adjusted_priority
        assert props["findings_should_fix"] == 1
        assert props["findings_consider"] == 0
        assert props["review_model"] == REVIEW_MODEL
        assert props["review_runtime_adapter"] == DEFAULT_REVIEW_ARM.runtime_adapter.value
        assert props["review_reasoning_effort"] == DEFAULT_REVIEW_ARM.reasoning_effort.value
        assert props["review_arm_fallback"] is False
        assert props["pr_additions"] == 120
        assert props["pr_deletions"] == 30
        assert props["pr_changed_files"] == 7
        assert props["pr_commits"] == 3
        assert props["pr_reviewable_additions"] == 80
        assert 90 <= props["duration_seconds"] < 600

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
        assert props["findings_total"] == 0

    def test_event_uuid_is_stable_across_retries(self) -> None:
        # A Temporal retry after a successful capture re-emits the event; a stable uuid lets
        # ingestion dedupe it instead of double-counting the review.
        report_id = self._review_report()
        tracking_input = self._tracking_input(report_id)

        with patch("products.review_hog.backend.temporal.activities.posthoganalytics.capture") as capture:
            _track_review_completed(tracking_input)
            _track_review_completed(tracking_input)

        first, second = capture.call_args_list
        assert first.kwargs["uuid"]
        assert first.kwargs["uuid"] == second.kwargs["uuid"]

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
