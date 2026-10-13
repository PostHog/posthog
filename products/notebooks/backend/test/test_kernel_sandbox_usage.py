from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.notebooks.backend.compute_pricing import get_compute_rates
from products.notebooks.backend.kernel_sandbox_usage import (
    KERNEL_SANDBOX_ENDED_EVENT,
    estimated_runtime_seconds,
    record_sandbox_ended,
    record_sandbox_ended_by_id,
)
from products.notebooks.backend.models import KernelRuntime


class TestEstimatedRuntimeSeconds(SimpleTestCase):
    @parameterized.expand(
        [
            ("destroyed_before_its_ttl", 600, False, 600),
            ("left_running_costs_until_its_ttl", 600, True, 3600),
            ("noticed_gone_after_its_ttl", 7200, False, 3600),
        ]
    )
    def test_estimated_runtime_seconds(
        self, _name: str, ended_after_seconds: int, sandbox_still_running: bool, expected_seconds: int
    ) -> None:
        created_at = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        seconds = estimated_runtime_seconds(
            created_at=created_at,
            ended_at=created_at + timedelta(seconds=ended_after_seconds),
            ttl_expires_at=created_at + timedelta(hours=1),
            sandbox_still_running=sandbox_still_running,
        )
        self.assertEqual(seconds, expected_seconds)


class TestRecordSandboxEnded(BaseTest):
    def _modal_runtime_with_an_hour_ttl(self) -> KernelRuntime:
        runtime = KernelRuntime.objects.create(
            team=self.team,
            user=self.user,
            notebook_short_id="abc123",
            status=KernelRuntime.Status.RUNNING,
            backend=KernelRuntime.Backend.MODAL,
            provisioned_cpu_cores=1,
            provisioned_memory_gb=2,
        )
        KernelRuntime.objects.filter(pk=runtime.pk).update(ttl_expires_at=runtime.created_at + timedelta(hours=1))
        runtime.refresh_from_db()
        return runtime

    @patch("products.notebooks.backend.kernel_sandbox_usage.report_user_or_team_action")
    def test_an_end_noticed_twice_is_reported_once(self, mock_report: MagicMock) -> None:
        runtime = self._modal_runtime_with_an_hour_ttl()
        copy_in_another_process = KernelRuntime.objects.get(pk=runtime.pk)

        with time_machine.travel(runtime.created_at + timedelta(minutes=30), tick=False):
            record_sandbox_ended(runtime, reason=KernelRuntime.Status.STOPPED, sandbox_still_running=False)
            record_sandbox_ended(
                copy_in_another_process, reason=KernelRuntime.Status.TIMED_OUT, sandbox_still_running=False
            )

        mock_report.assert_called_once()
        event, properties = mock_report.call_args[0]
        self.assertEqual(event, KERNEL_SANDBOX_ENDED_EVENT)
        self.assertEqual(properties["ended_reason"], KernelRuntime.Status.STOPPED)
        self.assertEqual(properties["estimated_runtime_seconds"], 1800)
        hourly_price = get_compute_rates().hourly_price(cpu_cores=1, memory_gb=2)
        self.assertEqual(properties["estimated_price_usd"], round(0.5 * hourly_price, 4))

    @patch("products.notebooks.backend.kernel_sandbox_usage.report_user_or_team_action")
    def test_an_end_whose_event_fails_is_reported_by_the_next_path(self, mock_report: MagicMock) -> None:
        mock_report.side_effect = [RuntimeError("capture queue unavailable"), None]
        runtime = self._modal_runtime_with_an_hour_ttl()

        record_sandbox_ended(runtime, reason=KernelRuntime.Status.STOPPED, sandbox_still_running=False)
        record_sandbox_ended_by_id(
            runtime.id,
            team_id=self.team.id,
            user_id=self.user.id,
            reason=KernelRuntime.Status.TIMED_OUT,
            sandbox_still_running=False,
        )

        self.assertEqual(mock_report.call_count, 2)
        self.assertEqual(mock_report.call_args[0][1]["ended_reason"], KernelRuntime.Status.TIMED_OUT)
        runtime.refresh_from_db()
        self.assertIsNotNone(runtime.ended_at)
