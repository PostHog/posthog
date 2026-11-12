import asyncio
from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, Mock, patch

from django.utils import timezone

from asgiref.sync import sync_to_async
from parameterized import parameterized
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from products.signals.backend.models import SignalReport
from products.signals.backend.research_recovery import STUCK_RESEARCH_CUTOFF, recover_stuck_research_reports
from products.signals.backend.temporal.summary import SignalReportSummaryWorkflow


class _FakeTemporal:
    def __init__(self, workflows: dict[str, WorkflowExecutionStatus | RPCStatusCode], on_describe=None) -> None:
        self.workflows = workflows
        self.on_describe = on_describe

    def get_workflow_handle(self, workflow_id: str) -> Mock:
        async def describe(**kwargs: object) -> Mock:
            if self.on_describe:
                await sync_to_async(self.on_describe)()
            status = self.workflows.get(workflow_id, RPCStatusCode.NOT_FOUND)
            if isinstance(status, RPCStatusCode):
                raise RPCError(status.name, status, b"")
            return Mock(status=status)

        return Mock(describe=describe)


class TestRecoverStuckResearchReports(BaseTest):
    def _in_progress_report(self, started_ago: timedelta) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.IN_PROGRESS,
            signal_count=3,
            run_count=2,
            last_run_at=timezone.now() - started_ago,
        )

    def _sweep(self, temporal: _FakeTemporal) -> int:
        with patch("products.signals.backend.research_recovery.async_connect", new=AsyncMock(return_value=temporal)):
            return recover_stuck_research_reports()

    @parameterized.expand(
        [
            (
                "stale_without_workflow",
                STUCK_RESEARCH_CUTOFF + timedelta(minutes=1),
                None,
                SignalReport.Status.CANDIDATE,
            ),
            (
                "stale_timed_out",
                STUCK_RESEARCH_CUTOFF + timedelta(minutes=1),
                WorkflowExecutionStatus.TIMED_OUT,
                SignalReport.Status.CANDIDATE,
            ),
            (
                "stale_terminated",
                STUCK_RESEARCH_CUTOFF + timedelta(minutes=1),
                WorkflowExecutionStatus.TERMINATED,
                SignalReport.Status.CANDIDATE,
            ),
            (
                "stale_still_running",
                STUCK_RESEARCH_CUTOFF + timedelta(minutes=1),
                WorkflowExecutionStatus.RUNNING,
                SignalReport.Status.IN_PROGRESS,
            ),
            (
                "stale_temporal_unavailable",
                STUCK_RESEARCH_CUTOFF + timedelta(minutes=1),
                RPCStatusCode.UNAVAILABLE,
                SignalReport.Status.IN_PROGRESS,
            ),
            ("not_stale", STUCK_RESEARCH_CUTOFF - timedelta(minutes=1), None, SignalReport.Status.IN_PROGRESS),
        ]
    )
    def test_sweep_moves_only_stale_reports_without_a_running_workflow(
        self,
        _name: str,
        started_ago: timedelta,
        workflow_status: WorkflowExecutionStatus | RPCStatusCode | None,
        expected_status: SignalReport.Status,
    ) -> None:
        report = self._in_progress_report(started_ago)
        workflows = {}
        if workflow_status is not None:
            workflows[SignalReportSummaryWorkflow.workflow_id_for(self.team.id, str(report.id))] = workflow_status

        recovered = self._sweep(_FakeTemporal(workflows))

        report.refresh_from_db()
        assert report.status == expected_status
        assert recovered == (1 if expected_status == SignalReport.Status.CANDIDATE else 0)
        # run_count feeds Temporal workflow IDs and must never roll back.
        assert report.run_count == 2

    def test_sweep_keeps_a_run_that_started_after_the_sweep_read_the_report(self) -> None:
        report = self._in_progress_report(STUCK_RESEARCH_CUTOFF + timedelta(minutes=1))

        def new_run_starts() -> None:
            SignalReport.objects.filter(id=report.id).update(last_run_at=timezone.now())

        recovered = self._sweep(_FakeTemporal({}, on_describe=new_run_starts))

        report.refresh_from_db()
        assert report.status == SignalReport.Status.IN_PROGRESS
        assert recovered == 0

    def test_sweep_recovers_completed_lookups_when_another_lookup_hangs(self) -> None:
        recovered_report = self._in_progress_report(STUCK_RESEARCH_CUTOFF + timedelta(minutes=2))
        hanging_report = self._in_progress_report(STUCK_RESEARCH_CUTOFF + timedelta(minutes=1))
        hanging_id = SignalReportSummaryWorkflow.workflow_id_for(self.team.id, str(hanging_report.id))

        class PartiallyResponsiveTemporal(_FakeTemporal):
            def get_workflow_handle(self, workflow_id: str) -> Mock:
                if workflow_id == hanging_id:

                    async def hang(**kwargs: object) -> Mock:
                        await asyncio.Event().wait()
                        raise AssertionError("unreachable")

                    return Mock(describe=hang)
                return super().get_workflow_handle(workflow_id)

        with patch("products.signals.backend.research_recovery.STUCK_RESEARCH_LOOKUP_TIMEOUT", 1):
            recovered = self._sweep(PartiallyResponsiveTemporal({}))

        recovered_report.refresh_from_db()
        hanging_report.refresh_from_db()
        assert recovered == 1
        assert recovered_report.status == SignalReport.Status.CANDIDATE
        assert hanging_report.status == SignalReport.Status.IN_PROGRESS
