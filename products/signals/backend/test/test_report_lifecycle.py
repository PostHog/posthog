from datetime import timedelta
from uuid import UUID

from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from products.signals.backend.models import InvalidStatusTransition, SignalReport


class TestReportMonitoringLifecycle(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        lookup = patch("products.signals.backend.report_content_gates.Team.objects.values_list").start()
        lookup.return_value.get.return_value = UUID("00000000-0000-0000-0000-000000000001")
        self.evaluate = patch(
            "products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True
        ).start()
        self.addCleanup(patch.stopall)

    @parameterized.expand(
        [
            (SignalReport.Status.READY, SignalReport.Status.POTENTIAL),
            (SignalReport.Status.PENDING_INPUT, SignalReport.Status.READY),
            (SignalReport.Status.FAILED, SignalReport.Status.POTENTIAL),
        ]
    )
    def test_implementation_time_anchors_the_period_until_implementation_reopens(
        self, initial_status: str, reopened_status: str
    ) -> None:
        report = SignalReport(team_id=7, status=initial_status, title="Checkout errors", summary="Investigated cause")
        merged_at = timezone.now() - timedelta(days=3)
        report.transition_to(SignalReport.Status.MONITORING, monitoring_started_at=merged_at)
        assert report.status == SignalReport.Status.MONITORING
        assert report.monitoring_started_at == merged_at
        assert report.title == "Checkout errors"
        assert report.summary == "Investigated cause"

        retry_at = timezone.now()
        assert report.transition_to(SignalReport.Status.MONITORING, monitoring_started_at=retry_at) == []
        assert report.monitoring_started_at == merged_at
        report.transition_to(SignalReport.Status.SUPPRESSED)
        assert report.restore_target_status() == SignalReport.Status.MONITORING
        report.transition_to(report.restore_target_status(), monitoring_started_at=retry_at)
        assert report.monitoring_started_at == merged_at

        report.transition_to(SignalReport.Status(reopened_status))
        self.assertIsNone(report.monitoring_started_at)
        if reopened_status == SignalReport.Status.READY:
            report.transition_to(SignalReport.Status.MONITORING, monitoring_started_at=retry_at)
            assert report.monitoring_started_at == retry_at

    @parameterized.expand([("missing", None), ("naive", "naive")])
    def test_entry_requires_an_explicit_aware_implementation_time(self, _name: str, invalid_time: str | None) -> None:
        report = SignalReport(team_id=7, status=SignalReport.Status.READY)
        timestamp = timezone.now().replace(tzinfo=None) if invalid_time == "naive" else None
        with self.assertRaises(ValueError):
            report.transition_to(SignalReport.Status.MONITORING, monitoring_started_at=timestamp)
        assert report.status == SignalReport.Status.READY
        assert report.monitoring_started_at is None

    @parameterized.expand([("disabled", False), ("unavailable", RuntimeError("flag service unavailable"))])
    def test_entry_requires_enablement(self, _name: str, flag_result: bool | Exception) -> None:
        self.evaluate.return_value = False
        self.evaluate.side_effect = flag_result if isinstance(flag_result, Exception) else None
        report = SignalReport(team_id=7, status=SignalReport.Status.READY)
        with self.assertRaises(InvalidStatusTransition):
            report.transition_to(SignalReport.Status.MONITORING, monitoring_started_at=timezone.now())
        assert report.status == SignalReport.Status.READY
        assert report.monitoring_started_at is None

    @parameterized.expand([("resolved",), ("closed",)])
    def test_finishing_verification_preserves_the_implementation_time(self, target: str) -> None:
        merged_at = timezone.now() - timedelta(days=3)
        report = SignalReport(team_id=7, status=SignalReport.Status.MONITORING, monitoring_started_at=merged_at)
        report.transition_to(SignalReport.Status(target))
        assert report.status == target
        assert report.monitoring_started_at == merged_at
