from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized
from temporalio.service import RPCError, RPCStatusCode

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import (
    ResolutionRunArtefact,
    ReviewIssueFinding,
    TurnMarkerArtefact,
    ValidationVerdict,
)
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH, REVIEW_MODE_FULL
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority, LineRange
from products.review_hog.backend.reviewer.progress import RESOLUTION_RUN_NOTE_AUTHOR, record_run_outcome
from products.review_hog.backend.temporal.client import WorkflowProbe
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import NoteArtefact

PR_URL = "https://github.com/PostHog/posthog/pull/5"
REQUESTED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
BEFORE = REQUESTED_AT - timedelta(hours=1)
AFTER = REQUESTED_AT + timedelta(minutes=2)
_PROBE = "products.review_hog.backend.pr_status.probe_workflow"


class TestPRStatusAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))
        self.url = f"/api/projects/{self.team.id}/review_hog/reviews/pr_status/"
        # Staleness checks read the clock, so pin it a few minutes after the request.
        self.enterContext(time_machine.travel(REQUESTED_AT + timedelta(minutes=5), tick=False))

    def _report(self, *, run_count: int = 1, last_run_at: datetime | None = BEFORE, **kwargs) -> ReviewReport:
        # Stored with other casing than the URL, because triggers store whatever casing they carried.
        return ReviewReport.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            repository="posthog/PostHog",
            pr_number=5,
            pr_url=PR_URL,
            head_branch="feat",
            base_branch="main",
            run_count=run_count,
            last_run_at=last_run_at,
            completed_head_sha="sha1" if run_count else None,
            status=kwargs.pop("status", ReviewReport.Status.IDLE),
            **kwargs,
        )

    def _turn(self, report: ReviewReport, run_index: int, review_mode: str, *, at: datetime) -> None:
        with time_machine.travel(at, tick=False):
            ReviewReportArtefact.add_turn_marker(
                team_id=self.team.id,
                report_id=str(report.id),
                content=TurnMarkerArtefact(
                    head_sha="sha1",
                    run_index=run_index,
                    review_mode=review_mode,
                    reviewhog_version="v",
                    reviewhog_fingerprint="f",
                ),
                attribution=ArtefactAttribution.system(),
            )

    def _get(self, probe: WorkflowProbe, **params: str) -> tuple[dict, MagicMock]:
        with patch(_PROBE, return_value=probe) as mock_probe:
            res = self.client.get(self.url, {"pr_url": PR_URL, **params})
        assert res.status_code == 200, res.json()
        return res.json(), mock_probe

    def _deep_turn_after_request(self) -> None:
        report = self._report(last_run_at=AFTER + timedelta(minutes=1))
        self._turn(report, 1, REVIEW_MODE_FULL, at=AFTER)

    def _deep_turn_before_then_standard_dropped(self) -> None:
        report = self._report()
        self._turn(report, 1, REVIEW_MODE_FULL, at=BEFORE - timedelta(minutes=5))
        with time_machine.travel(AFTER, tick=False):
            record_run_outcome(
                self.team.id,
                str(report.id),
                stage="review",
                outcome="skipped",
                reason="flash_after_full",
                run_index=2,
                review_mode=REVIEW_MODE_FLASH,
            )

    def _failed_first_turn(self) -> None:
        report = self._report(run_count=0, last_run_at=None)
        with time_machine.travel(AFTER, tick=False):
            record_run_outcome(
                self.team.id,
                str(report.id),
                stage="review",
                outcome="failed",
                reason="review_failed",
                run_index=1,
                review_mode=REVIEW_MODE_FULL,
            )

    def _deep_turn_before_request(self) -> None:
        report = self._report()
        self._turn(report, 1, REVIEW_MODE_FULL, at=BEFORE - timedelta(minutes=5))

    def _completed_resolution_after_request(self) -> None:
        report = self._report()
        with time_machine.travel(AFTER, tick=False):
            ReviewReportArtefact.append_resolution_run(
                team_id=self.team.id,
                report_id=str(report.id),
                content=ResolutionRunArtefact(total=1, thread_ids=["PRRT_1"]),
                attribution=ArtefactAttribution.system(),
            )
        with time_machine.travel(AFTER + timedelta(minutes=1), tick=False):
            ReviewReportArtefact.add_log(
                team_id=self.team.id,
                report_id=str(report.id),
                content=NoteArtefact(note="Resolution run on PR #5: done", author=RESOLUTION_RUN_NOTE_AUTHOR),
                attribution=ArtefactAttribution.system(),
            )

    def _deep_turn_publishing(self) -> None:
        # Finalize already counted the turn, but the report stays ACTIVE until the publish lands.
        report = self._report(last_run_at=AFTER + timedelta(minutes=1), status=ReviewReport.Status.ACTIVE)
        self._turn(report, 1, REVIEW_MODE_FULL, at=AFTER)

    def _deep_turn_publish_failed(self) -> None:
        report = self._report(last_run_at=AFTER + timedelta(minutes=1))
        self._turn(report, 1, REVIEW_MODE_FULL, at=AFTER)
        with time_machine.travel(AFTER + timedelta(minutes=2), tick=False):
            record_run_outcome(
                self.team.id,
                str(report.id),
                stage="review",
                outcome="failed",
                reason="review_failed",
                run_index=1,
                review_mode=REVIEW_MODE_FULL,
            )

    def _joined_resolution_completed_after_request(self) -> None:
        # A resolve_only trigger joins a resolution that started before the request.
        report = self._report()
        with time_machine.travel(BEFORE, tick=False):
            ReviewReportArtefact.append_resolution_run(
                team_id=self.team.id,
                report_id=str(report.id),
                content=ResolutionRunArtefact(total=1, thread_ids=["PRRT_1"]),
                attribution=ArtefactAttribution.system(),
            )
        with time_machine.travel(AFTER, tick=False):
            ReviewReportArtefact.add_log(
                team_id=self.team.id,
                report_id=str(report.id),
                content=NoteArtefact(note="Resolution run on PR #5: done", author=RESOLUTION_RUN_NOTE_AUTHOR),
                attribution=ArtefactAttribution.system(),
            )

    def _resolution_skipped_after_request(self) -> None:
        report = self._report()
        with time_machine.travel(AFTER, tick=False):
            record_run_outcome(
                self.team.id, str(report.id), stage="resolution", outcome="skipped", reason="no_unresolved_threads"
            )

    @parameterized.expand(
        [
            ("completed_deep", "_deep_turn_after_request", "review", WorkflowProbe.NOT_RUNNING, ("completed", None, 1)),
            (
                "deep_covers_standard",
                "_deep_turn_after_request",
                "flash",
                WorkflowProbe.NOT_RUNNING,
                ("completed", None, 1),
            ),
            (
                "standard_dropped_after_deep",
                "_deep_turn_before_then_standard_dropped",
                "flash",
                WorkflowProbe.NOT_RUNNING,
                ("skipped", "flash_after_full", 2),
            ),
            ("failed_turn", "_failed_first_turn", "review", WorkflowProbe.NOT_RUNNING, ("failed", "review_failed", 1)),
            # The queue can retry a failed run, so a failure is final only once nothing runs.
            ("failed_turn_retrying", "_failed_first_turn", "review", WorkflowProbe.RUNNING, ("pending", None, None)),
            ("publishing", "_deep_turn_publishing", "review", WorkflowProbe.NOT_RUNNING, ("pending", None, None)),
            (
                "publish_failed",
                "_deep_turn_publish_failed",
                "review",
                WorkflowProbe.NOT_RUNNING,
                ("failed", "review_failed", 1),
            ),
            (
                "nothing_ran_or_queued",
                "_deep_turn_before_request",
                "review",
                WorkflowProbe.NOT_RUNNING,
                ("failed", "no_matching_run", None),
            ),
            ("queued", "_deep_turn_before_request", "review", WorkflowProbe.RUNNING, ("pending", None, None)),
            # A Temporal error must never read as "nothing runs", or a queued request would read as failed.
            ("temporal_error", "_deep_turn_before_request", "review", WorkflowProbe.UNKNOWN, ("unknown", None, None)),
            (
                "resolve_only_completed",
                "_completed_resolution_after_request",
                "resolve_only",
                WorkflowProbe.NOT_RUNNING,
                ("completed", None, None),
            ),
            (
                "resolve_only_joined_run_completed",
                "_joined_resolution_completed_after_request",
                "resolve_only",
                WorkflowProbe.NOT_RUNNING,
                ("completed", None, None),
            ),
            (
                "resolve_only_skipped",
                "_resolution_skipped_after_request",
                "resolve_only",
                WorkflowProbe.NOT_RUNNING,
                ("skipped", "no_unresolved_threads", None),
            ),
        ]
    )
    def test_request_outcome(
        self,
        _name: str,
        setup: str,
        run_mode: str,
        probe: WorkflowProbe,
        expected: tuple[str, str | None, int | None],
    ) -> None:
        getattr(self, setup)()

        body, _ = self._get(probe, requested_at=REQUESTED_AT.isoformat(), run_mode=run_mode)

        outcome = body["request_outcome"]
        assert (outcome["status"], outcome["reason"], outcome["run_index"]) == expected
        assert outcome["review_id"] == body["report_id"]

    @parameterized.expand(
        [
            ("no_report", None, WorkflowProbe.NOT_RUNNING, "not_reviewed", True),
            ("completed_review", ReviewReport.Status.IDLE, WorkflowProbe.NOT_RUNNING, "idle", True),
            ("queued", ReviewReport.Status.IDLE, WorkflowProbe.RUNNING, "queued", True),
            ("temporal_error", ReviewReport.Status.IDLE, WorkflowProbe.UNKNOWN, "unknown", True),
            # The database already shows a running turn, so Temporal is not asked.
            ("running_turn", ReviewReport.Status.ACTIVE, WorkflowProbe.UNKNOWN, "reviewing", False),
        ]
    )
    def test_state(
        self, _name: str, report_status: str | None, probe: WorkflowProbe, expected: str, probed: bool
    ) -> None:
        if report_status is not None:
            self._report(status=report_status)

        body, mock_probe = self._get(probe)

        assert body["state"] == expected
        assert body["request_outcome"] is None
        assert mock_probe.called is probed
        if probed:
            # The probe asks for the root team's workflow, whatever casing the URL carries.
            assert mock_probe.call_args_list[0].args[0] == f"review-pr:{self.team.id}:posthog/posthog:5"

    def test_probes_temporal_with_a_short_deadline(self) -> None:
        self._report()
        handle = MagicMock()
        handle.describe = AsyncMock(side_effect=RPCError("deadline", RPCStatusCode.DEADLINE_EXCEEDED, b""))

        with patch("products.review_hog.backend.temporal.client.sync_connect") as mock_connect:
            mock_connect.return_value.get_workflow_handle.return_value = handle
            res = self.client.get(self.url, {"pr_url": PR_URL})

        assert res.json()["state"] == "unknown"
        assert [call.kwargs["rpc_timeout"] for call in handle.describe.call_args_list] == [timedelta(seconds=2)] * 2

    def test_resolving_state_and_latest_review(self) -> None:
        report = self._report(
            status=ReviewReport.Status.ACTIVE, status_comment_id=77, published_head_shas={"1": "sha1"}
        )
        self._turn(report, 1, REVIEW_MODE_FULL, at=BEFORE - timedelta(minutes=5))
        for key, priority, is_valid in [
            ("1-a", IssuePriority.MUST_FIX, True),
            ("1-b", IssuePriority.CONSIDER, True),
            ("1-c", IssuePriority.MUST_FIX, False),
        ]:
            ReviewReportArtefact.append_finding(
                team_id=self.team.id,
                report_id=str(report.id),
                content=ReviewIssueFinding(
                    issue_key=key,
                    run_index=1,
                    title="t",
                    file="f.py",
                    lines=[LineRange(start=1)],
                    body="b",
                    suggestion="s",
                    priority=priority,
                ),
                attribution=ArtefactAttribution.system(),
            )
            ReviewReportArtefact.append_verdict(
                team_id=self.team.id,
                report_id=str(report.id),
                content=ValidationVerdict(issue_key=key, is_valid=is_valid, argumentation="a"),
                attribution=ArtefactAttribution.system(),
            )
        ReviewReportArtefact.append_resolution_run(
            team_id=self.team.id,
            report_id=str(report.id),
            content=ResolutionRunArtefact(total=1, thread_ids=["PRRT_1"]),
            attribution=ArtefactAttribution.system(),
        )

        body, mock_probe = self._get(WorkflowProbe.NOT_RUNNING)

        assert body["state"] == "resolving"
        mock_probe.assert_not_called()
        assert body["repository"] == "posthog/PostHog"
        assert body["latest_review"] == {
            "id": str(report.id),
            "review_mode": "full",
            "head_sha": "sha1",
            "run_index": 1,
            "completed_at": "2026-07-01T11:00:00Z",
            "must_fix_count": 1,
            "should_fix_count": 0,
            "consider_count": 1,
            "turn_published": True,
            "status_comment_url": f"{PR_URL}#issuecomment-77",
        }
        assert body["latest_resolution"]["status"] == "resolving"

    def test_rejects_a_url_that_is_not_a_pull_request(self) -> None:
        res = self.client.get(self.url, {"pr_url": "https://github.com/PostHog/posthog/issues/5"})

        assert res.status_code == 400
