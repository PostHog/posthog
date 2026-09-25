from datetime import timedelta
from io import StringIO
from types import SimpleNamespace

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from parameterized import parameterized

from products.signals.backend.management.commands.rerun_signal_report import Command
from products.signals.backend.models import SignalReport


class TestRerunSignalReportCommand(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout failure",
            summary="Fix the checkout path",
            signal_count=1,
            run_count=2,
        )
        quota_patch = patch(
            "products.signals.backend.management.commands.rerun_signal_report.self_driving_quota_gate",
            return_value=SimpleNamespace(enforced=False),
        )
        quota_patch.start()
        self.addCleanup(quota_patch.stop)
        usage_patch = patch(
            "products.signals.backend.management.commands.rerun_signal_report.task_run_usage_limited",
            return_value=False,
        )
        usage_patch.start()
        self.addCleanup(usage_patch.stop)
        trial_patch = patch(
            "products.signals.backend.management.commands.rerun_signal_report.self_driving_free_trial_enabled",
            return_value=False,
        )
        trial_patch.start()
        self.addCleanup(trial_patch.stop)

    def command(self, *, execute: bool = False) -> str:
        output = StringIO()
        call_command(
            "rerun_signal_report",
            team_id=self.team.id,
            report_id=self.report.id,
            user_id=self.user.id,
            execute=execute,
            stdout=output,
        )
        return output.getvalue()

    @patch.object(Command, "_start_workflow", new_callable=AsyncMock)
    @patch.object(Command, "_workflow_is_running", new_callable=AsyncMock, return_value=False)
    def test_dry_run_does_not_promote_or_start(self, _running: AsyncMock, start: AsyncMock) -> None:
        assert "Dry run" in self.command()
        self.report.refresh_from_db()
        assert self.report.status == SignalReport.Status.READY
        start.assert_not_awaited()

    @parameterized.expand(
        [
            ("ready", SignalReport.Status.READY),
            ("candidate", SignalReport.Status.CANDIDATE),
            ("failed", SignalReport.Status.FAILED),
            ("pending_input", SignalReport.Status.PENDING_INPUT),
            ("resolved", SignalReport.Status.RESOLVED),
            ("potential", SignalReport.Status.POTENTIAL),
        ]
    )
    @patch.object(Command, "_start_workflow", new_callable=AsyncMock)
    @patch.object(Command, "_workflow_is_running", new_callable=AsyncMock, return_value=False)
    def test_execute_starts_fresh_research_with_implementation_request(
        self, _name: str, status: SignalReport.Status, _running: AsyncMock, start: AsyncMock
    ) -> None:
        self.report.status = status
        self.report.save(update_fields=["status"])
        previous_promoted_at = self.report.promoted_at
        assert "Started research" in self.command(execute=True)
        self.report.refresh_from_db()
        assert self.report.status == SignalReport.Status.CANDIDATE
        if status == SignalReport.Status.CANDIDATE:
            assert self.report.promoted_at != previous_promoted_at
        start.assert_awaited_once()
        assert start.await_args is not None
        inputs = start.await_args.args[0]
        assert inputs.report_id == str(self.report.id)
        assert inputs.requested_implementation_user_id == self.user.id
        assert inputs.requested_after_run_count == 2

    @patch.object(Command, "_workflow_is_running", new_callable=AsyncMock, return_value=True)
    def test_running_summary_workflow_blocks_restart(self, _running: AsyncMock) -> None:
        try:
            self.command(execute=True)
        except CommandError as error:
            assert "already has a running summary workflow" in str(error)
        else:
            raise AssertionError("The command started alongside an active summary workflow")
        self.report.refresh_from_db()
        assert self.report.status == SignalReport.Status.READY

    @parameterized.expand(
        [
            ("ready", SignalReport.Status.READY),
            ("failed", SignalReport.Status.FAILED),
            ("candidate", SignalReport.Status.CANDIDATE),
        ]
    )
    @patch.object(Command, "_start_workflow", new_callable=AsyncMock, side_effect=RuntimeError("start failed"))
    @patch.object(Command, "_workflow_is_running", new_callable=AsyncMock, return_value=False)
    def test_failed_workflow_start_restores_original_status(
        self, _name: str, status: SignalReport.Status, _running: AsyncMock, _start: AsyncMock
    ) -> None:
        self.report.status = status
        self.report.promoted_at = timezone.now() - timedelta(minutes=1)
        self.report.save(update_fields=["status", "promoted_at"])
        original_promoted_at = self.report.promoted_at
        try:
            self.command(execute=True)
        except CommandError as error:
            assert f"restored the report to {status}" in str(error)
        else:
            raise AssertionError("A failed workflow start appeared successful")
        self.report.refresh_from_db()
        assert self.report.status == status
        assert self.report.promoted_at == original_promoted_at
