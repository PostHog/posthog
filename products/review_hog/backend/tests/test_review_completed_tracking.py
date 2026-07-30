from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

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
    _track_review_completed,
    _track_review_completed_safe,
)
from products.tasks.backend.models import Task, TaskRun

_PR_URL = "https://github.com/o/r/pull/7"
_WORKFLOW_ID = "review-pr:2:o/r:7"


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
        return upsert_review_report(team_id=self.team.id, repository="o/r", pr_url=_PR_URL, pr_metadata=_pr_metadata())

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
                "1-1-1": IssueValidation(is_valid=True, argumentation="real", category="bug"),
                "1-1-2": IssueValidation(is_valid=False, argumentation="not real", category="bug"),
            },
        )

        with patch("products.review_hog.backend.temporal.activities.posthoganalytics.capture") as capture:
            _track_review_completed(self._tracking_input(report_id, published=published), _WORKFLOW_ID)

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
        assert props["pr_additions"] == 120
        assert props["pr_deletions"] == 30
        assert props["pr_changed_files"] == 7
        assert props["pr_commits"] == 3
        assert props["pr_reviewable_additions"] == 80
        assert 90 <= props["duration_seconds"] < 600
        # No sandbox runs for this turn — the cost-linkage properties record an empty turn, not null.
        assert props["sandbox_task_ids"] == []
        assert props["sandbox_run_count"] == 0
        assert props["llm_total_tokens"] == 0

    def test_missing_snapshot_still_captures_without_pr_size(self) -> None:
        # A turn whose pr_snapshot is unavailable must still count as a review — size props go
        # null rather than the capture (and with it the review count) being lost.
        report_id = self._review_report()

        with patch("products.review_hog.backend.temporal.activities.posthoganalytics.capture") as capture:
            _track_review_completed(self._tracking_input(report_id, published=False), _WORKFLOW_ID)

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
            _track_review_completed(tracking_input, _WORKFLOW_ID)
            _track_review_completed(tracking_input, _WORKFLOW_ID)

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
            _track_review_completed_safe(self._tracking_input(report_id), _WORKFLOW_ID)

    def test_collects_turn_sandbox_usage(self) -> None:
        # Cost-per-PR dashboards join this event to $ai_generation through sandbox_task_ids — a
        # broken prefix lookup or token summing silently zeroes them, and a loose prefix match
        # would leak PR 74's runs into PR 7's turn.
        report_id = self._review_report()
        task = Task.objects.create(team=self.team, title="t", origin_product=Task.OriginProduct.REVIEW_HOG)
        TaskRun.objects.create(
            task=task,
            team=self.team,
            state={
                "workflow_id_prefix": f"{_WORKFLOW_ID}:chunking",
                "token_usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            },
        )
        TaskRun.objects.create(
            task=task,
            team=self.team,
            state={
                "workflow_id_prefix": f"{_WORKFLOW_ID}/review:issues-review-p1-c1",
                "token_usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
            },
        )
        # PR 74 shares PR 7's prefix as a string — the separator-suffixed match must exclude it.
        neighbour_pr = Task.objects.create(team=self.team, title="t", origin_product=Task.OriginProduct.REVIEW_HOG)
        TaskRun.objects.create(
            task=neighbour_pr,
            team=self.team,
            state={"workflow_id_prefix": f"{_WORKFLOW_ID}4:chunking", "token_usage": {"input_tokens": 100}},
        )
        # A prior turn's run for the same PR sits before this turn's window.
        stale = TaskRun.objects.create(
            task=task, team=self.team, state={"workflow_id_prefix": f"{_WORKFLOW_ID}:chunking"}
        )
        TaskRun.objects.filter(id=stale.id).update(created_at=datetime.now(UTC) - timedelta(hours=2))

        with patch("products.review_hog.backend.temporal.activities.posthoganalytics.capture") as capture:
            # Real workflow ids carry the repo's casing; the stored prefixes are lowercased.
            _track_review_completed(self._tracking_input(report_id), _WORKFLOW_ID.upper())

        props = capture.call_args.kwargs["properties"]
        assert props["sandbox_task_ids"] == [str(task.id)]
        assert props["sandbox_run_count"] == 2
        assert props["llm_input_tokens"] == 11
        assert props["llm_output_tokens"] == 7
        assert props["llm_total_tokens"] == 18
