from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.models import SignalReport, SignalReportCheck
from products.signals.backend.report_check_monitoring_timing import MonitoringCheckTiming
from products.signals.backend.serializers import SignalReportCheckSerializer


class TestMonitoringCheckTiming(SimpleTestCase):
    @parameterized.expand([("enabled", True), ("disabled", False)])
    def test_serialized_timing_respects_the_request_rollout_without_revealing_query_data(
        self, _name: str, enabled: bool
    ) -> None:
        now = datetime(2026, 10, 20, tzinfo=UTC)
        report = SignalReport(team_id=1, status="monitoring", monitoring_started_at=now)
        check = SignalReportCheck(
            team_id=1,
            report=report,
            kind="metric_threshold",
            status="active",
            config={
                "monitoring": {"reference_period_minutes": 1440, "threshold_scaling": "fixed"},
                "comparison": {"operator": "lte", "value": 10},
                "query": {"kind": "InsightVizNode"},
            },
            soak_minutes=1440,
            measurement_start_at=now,
            next_run_at=now + timedelta(hours=6),
            expires_at=now + timedelta(days=90),
        )

        data = SignalReportCheckSerializer(
            check,
            context={"report_monitoring_enabled_by_team": {1: enabled}, "report_check_timing_now": now},
        ).data

        assert data["config"]["query"] is None
        assert ("monitoring_timing" in data) is enabled
        if enabled:
            assert data["monitoring_timing"] == {
                "state": "scheduled",
                "started_at": "2026-10-20T00:00:00Z",
                "ends_at": "2026-10-21T00:00:00Z",
                "next_measurement_at": "2026-10-20T06:00:00Z",
            }

    @parameterized.expand(
        [
            ("scheduled", 6, 12, "scheduled", True),
            ("due", 12, 12, "due", True),
            ("overdue", 13, 12, "due", True),
            ("last_sample_finished", 20, 24, "no_interim_measurements", False),
            ("exact_deadline", 24, 24, "window_ended", False),
            ("late_tick", 30, 24, "window_ended", False),
            ("query_error_retry_past_end", 20, 26, "no_interim_measurements", False),
        ]
    )
    def test_deadline_is_not_presented_as_another_measurement(
        self, _name: str, elapsed_hours: int, due_hours: int, state: str, has_next: bool
    ) -> None:
        start = datetime(2026, 10, 20, tzinfo=UTC)
        report = SignalReport(team_id=1, status="monitoring", monitoring_started_at=start)
        check = SignalReportCheck(
            team_id=1,
            report=report,
            kind="metric_threshold",
            status="active",
            config={"monitoring": {"reference_period_minutes": 1440, "threshold_scaling": "fixed"}},
            soak_minutes=1440,
            measurement_start_at=start,
            next_run_at=start + timedelta(hours=due_hours),
            expires_at=start + timedelta(days=90),
        )

        timing = MonitoringCheckTiming.for_check(check, now=start + timedelta(hours=elapsed_hours))

        assert timing is not None
        assert timing.state == state
        assert timing.ends_at == start + timedelta(days=1)
        assert timing.next_measurement_at == (check.next_run_at if has_next else None)

    @parameterized.expand(
        [
            ("agent", "agent", "active", 1440, True, True, "paused"),
            ("legacy_metric", "metric_threshold", "active", 1440, False, True, "paused"),
            ("pending", "metric_threshold", "pending", 1440, True, True, "waiting"),
            ("missing_start", "metric_threshold", "active", 1440, True, False, "unavailable"),
            ("missing_soak", "metric_threshold", "active", None, True, True, "unavailable"),
            ("zero_soak", "metric_threshold", "active", 0, True, True, "window_ended"),
            ("terminal", "metric_threshold", "errored", 1440, True, True, None),
        ]
    )
    def test_only_armed_monitoring_metrics_offer_measurements(
        self, _name: str, kind: str, status: str, soak: int | None, definition: bool, has_start: bool, state: str | None
    ) -> None:
        now = datetime(2026, 10, 20, tzinfo=UTC)
        start = now - timedelta(hours=6)
        report = SignalReport(team_id=1, status="monitoring", monitoring_started_at=start if has_start else None)
        check = SignalReportCheck(
            team_id=1,
            report=report,
            kind=kind,
            status=status,
            config={"monitoring": {"threshold_scaling": "fixed"}} if definition else {},
            soak_minutes=soak,
            measurement_start_at=start,
            next_run_at=now,
            expires_at=now + timedelta(days=1),
        )

        timing = MonitoringCheckTiming.for_check(check, now=now)

        assert (timing.state if timing else None) == state
        assert timing is None or timing.next_measurement_at is None

    @parameterized.expand(
        [
            ("resolved", "resolved", None, 90, None),
            ("reopened", "ready", None, 90, None),
            ("archived", "suppressed", "monitoring", 90, "archived"),
            ("expired", "monitoring", None, 0, "expiry_reached"),
            ("safety_horizon", "monitoring", None, 90, "expiry_reached", 90),
        ]
    )
    def test_report_lifecycle_and_expiry_pause_measurement_promises(
        self,
        _name: str,
        report_status: str,
        prior_status: str | None,
        expiry_days: int,
        state: str | None,
        monitoring_age_days: int = 0,
    ) -> None:
        now = datetime(2026, 10, 20, tzinfo=UTC)
        report = SignalReport(
            team_id=1,
            status=report_status,
            status_before_suppression=prior_status,
            monitoring_started_at=now - timedelta(days=monitoring_age_days),
        )
        check = SignalReportCheck(
            team_id=1,
            report=report,
            kind="metric_threshold",
            status="active",
            config={"monitoring": {"threshold_scaling": "fixed"}},
            soak_minutes=1440,
            measurement_start_at=now,
            next_run_at=now,
            expires_at=now + timedelta(days=expiry_days),
        )

        timing = MonitoringCheckTiming.for_check(check, now=now)

        assert (timing.state if timing else None) == state
        assert timing is None or timing.next_measurement_at is None
