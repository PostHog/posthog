import json
import time
from datetime import timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, Mock, patch

from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import ActionabilityChoice, NoteArtefact, Priority
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportCheck,
    SignalReportMonitoringAttempt,
    SignalReportMonitoringResult,
)
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.report_monitoring_research import (
    MonitoringResearch,
    dispatch_due_monitoring_research,
    dispatch_monitoring_research,
)
from products.signals.backend.temporal.agentic.report import RunAgenticReportOutput
from products.signals.backend.temporal.monitoring_research import research_monitoring_attempt_activity
from products.signals.backend.temporal.report_safety_judge import SafetyJudgeOutput


class TestMonitoringResearch(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = timezone.now()
        self.enterContext(time_machine.travel(self.now, tick=False))
        self.flag = self.enterContext(
            patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True)
        )
        self.report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.CLOSED,
            title="Checkout recovery",
            summary="Checkout completion remains unverified.",
            monitoring_started_at=self.now - timedelta(hours=1),
        )
        assert self.report.monitoring_started_at is not None
        self.attempt = SignalReportMonitoringAttempt.objects.for_team(self.team.id).create(
            team=self.team,
            report=self.report,
            monitoring_started_at=self.report.monitoring_started_at,
            check_versions={},
            aggregation_state="failed",
            aggregation_reason="A check failed with sufficient evidence.",
            research_requested_at=self.now,
        )
        self.request = MonitoringResearch(team_id=self.team.id, report_id=self.report.id, attempt_id=self.attempt.id)

    def result(
        self, choice: ActionabilityChoice = ActionabilityChoice.IMMEDIATELY_ACTIONABLE
    ) -> RunAgenticReportOutput:
        return RunAgenticReportOutput(
            title="Investigate checkout completion",
            summary="Verify the deployment and checkout population.",
            choice=choice,
            priority=Priority.P2,
            explanation="The saved evidence needs investigation.",
            already_addressed=False,
            repository="example/repository",
        )

    @parameterized.expand(
        [
            (ActionabilityChoice.IMMEDIATELY_ACTIONABLE, SignalReport.Status.READY),
            (ActionabilityChoice.REQUIRES_HUMAN_INPUT, SignalReport.Status.PENDING_INPUT),
            (ActionabilityChoice.NOT_ACTIONABLE, SignalReport.Status.POTENTIAL),
        ]
    )
    def test_retry_reuses_successor_and_preserves_original_outcome(
        self, choice: ActionabilityChoice, expected_status: str
    ) -> None:
        successor = self.request.prepare()
        assert successor is not None
        retried = self.request.prepare()
        assert retried is not None and retried.id == successor.id
        self.request.finish(self.result(choice))
        self.request.finish(self.result(choice))
        assert self.request.prepare() is None
        successor.refresh_from_db()
        self.report.refresh_from_db()
        self.attempt.refresh_from_db()
        assert successor.status == expected_status
        assert successor.title == "Investigate checkout completion"
        assert self.report.status == SignalReport.Status.CLOSED
        assert self.report.summary == "Checkout completion remains unverified."
        assert self.attempt.aggregation_state == "failed"
        assert self.attempt.research_requested_at == self.now
        links = SignalReportArtefact.objects.filter(team_id=self.team.id, report_id=successor.id, type="report_link")
        assert links.count() == 1
        assert json.loads(links.get().content)["report_id"] == str(self.report.id)
        assert SignalReport.objects.filter(team_id=self.team.id).count() == 2

    @parameterized.expand(
        [
            (change, failure)
            for change in ("ready", "resolved", "suppressed", "new_attempt", "disabled")
            for failure in (False, True)
        ]
    )
    def test_late_completion_cannot_attach_to_changed_report(self, change: str, failure: bool) -> None:
        successor = self.request.prepare()
        assert successor is not None
        if change == "disabled":
            self.flag.return_value = False
        elif change == "new_attempt":
            SignalReport.objects.filter(id=self.report.id).update(monitoring_started_at=self.now)
        else:
            SignalReport.objects.filter(id=self.report.id).update(status=change)
        if failure:
            self.request.fail("Research could not finish")
        else:
            self.request.finish(self.result())
        assert self.request.prepare() is None
        assert not SignalReportArtefact.objects.filter(report_id=successor.id, type="report_link").exists()
        successor.refresh_from_db()
        assert successor.title is None

    def test_context_retains_attempt_and_assessment_evidence(self) -> None:
        assert self.report.monitoring_started_at is not None
        check = SignalReportCheck.objects.for_team(self.team.id).create(
            team=self.team,
            report=self.report,
            title="Checkout completions",
            kind="metric_threshold",
            config={},
            next_run_at=self.now,
            expires_at=self.now + timedelta(days=1),
        )
        SignalReportMonitoringResult.objects.for_team(self.team.id).create(
            team=self.team,
            report=self.report,
            attempt=self.attempt,
            report_check=check,
            submission_id=uuid4(),
            definition_version="original-definition",
            window_start=self.report.monitoring_started_at,
            window_end=self.now,
            evaluated_at=self.now,
            outcome="errored",
            evidence_status="errored",
            evidence_reason="Query failed",
            explanation="No final measurement was available",
            evidence_refs=["query-run:example"],
        )
        SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=NoteArtefact(
                note="Assessment could not establish whether the deployment reached the affected population."
            ),
            attribution=ArtefactAttribution.system(),
        )
        context = self.request.context()
        assert "Uncertainty is not proof" in context
        data = json.loads(context.split("\n\n", 1)[1])
        assert data["attempt_id"] == str(self.attempt.id)
        assert data["attempts"][0]["aggregation_reason"] == self.attempt.aggregation_reason
        assert "affected population" in data["artefacts"][0]["content"]
        assert data["results"][0]["evidence_status"] == "errored"
        assert data["results"][0]["evidence_refs"] == ["query-run:example"]

    def test_exhausted_research_is_linked_once_without_restarting(self) -> None:
        successor = self.request.prepare()
        assert successor is not None
        self.request.fail("Research exhausted its technical retries")
        self.request.fail("Duplicate failure")
        self.request.finish(self.result())
        assert self.request.prepare() is None
        successor.refresh_from_db()
        assert successor.status == SignalReport.Status.FAILED
        assert successor.error == "Research exhausted its technical retries"
        assert SignalReportArtefact.objects.filter(report_id=successor.id, type="report_link").count() == 1

    def test_worker_researches_the_prior_attempt_into_the_reserved_successor(self) -> None:
        runner = AsyncMock(return_value=self.result())
        module = "products.signals.backend.temporal.monitoring_research"
        with (
            patch(
                "products.signals.backend.temporal.summary.check_report_quota_gate_activity",
                new=AsyncMock(return_value=False),
            ),
            patch(
                f"{module}.report_safety_judge_activity",
                new=AsyncMock(return_value=SafetyJudgeOutput(safe=True, explanation=None)),
            ),
            patch(f"{module}.github_optional_pilot_activity", new=AsyncMock(return_value=False)),
            patch(
                f"{module}.select_repository_activity",
                new=AsyncMock(
                    return_value=RepoSelectionResult(
                        repository="example/repository", reason="Original implementation repository"
                    )
                ),
            ),
            patch(f"{module}.run_agentic_report_activity", new=runner),
        ):
            async_to_sync(research_monitoring_attempt_activity)(self.request)
            async_to_sync(research_monitoring_attempt_activity)(self.request)
        assert runner.await_count == 1
        assert runner.await_args is not None
        research = runner.await_args.args[0]
        assert research.report_id == str(self.attempt.id)
        assert str(self.report.id) in research.signals[0].content
        assert "Checkout completion remains unverified" in research.signals[0].content
        successor = SignalReport.objects.get(team_id=self.team.id, id=self.attempt.id)
        assert successor.summary == self.result().summary
        assert SignalReportArtefact.objects.filter(report_id=successor.id, type="report_link").count() == 1

    def test_failed_dispatch_recovers_with_same_workflow_and_successor(self) -> None:
        start = AsyncMock(side_effect=[RuntimeError("Temporal unavailable"), None])
        with patch(
            "posthog.temporal.common.client.async_connect", new=AsyncMock(return_value=Mock(start_workflow=start))
        ):
            with self.assertRaisesRegex(RuntimeError, "Temporal unavailable"):
                dispatch_monitoring_research(self.request)
            dispatch_due_monitoring_research(deadline=time.monotonic() + 10, limit=1)
            assert start.await_count == 2
            assert {call.kwargs["id"] for call in start.await_args_list} == {self.request.workflow_id}
            assert SignalReport.objects.filter(id=self.attempt.id).count() == 1
            self.request.finish(self.result())
            dispatch_due_monitoring_research(deadline=time.monotonic() + 10, limit=1)
            assert start.await_count == 2

    def test_running_attempt_does_not_starve_undelivered_request(self) -> None:
        second_report = SignalReport.objects.create(team=self.team, status="closed", monitoring_started_at=self.now)
        second = SignalReportMonitoringAttempt.objects.for_team(self.team.id).create(
            team=self.team, report=second_report, monitoring_started_at=self.now, research_requested_at=self.now
        )
        start = AsyncMock()
        with patch(
            "posthog.temporal.common.client.async_connect", new=AsyncMock(return_value=Mock(start_workflow=start))
        ):
            dispatch_due_monitoring_research(deadline=time.monotonic() + 10, limit=1)
            dispatch_due_monitoring_research(deadline=time.monotonic() + 10, limit=1)
        assert {call.kwargs["id"] for call in start.await_args_list} == {
            self.request.workflow_id,
            MonitoringResearch(team_id=self.team.id, report_id=second_report.id, attempt_id=second.id).workflow_id,
        }
