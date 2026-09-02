from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Team

from products.signals.backend.daily_limit import DailyReportLimitGate, daily_report_limit_gate
from products.signals.backend.models import SignalReport, SignalTeamConfig

DAILY_LIMIT_MODULE = "products.signals.backend.daily_limit"


class TestDailyReportLimitGate(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # A SignalTeamConfig is auto-created for every team via register_team_extension_signal.
        self.config = SignalTeamConfig.objects.get(team=self.team)

    def _set_limit(self, limit: int | None) -> None:
        self.config.max_reports_per_day = limit
        self.config.save(update_fields=["max_reports_per_day"])

    def _visible_report(self, first_visible_at: datetime | None) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, first_visible_at=first_visible_at
        )

    def test_no_limit_short_circuits_without_counting(self):
        # The count query must stay off the fleet-wide hot path (every buffer flush runs this
        # gate): with no limit configured, only the single limit read may execute.
        self._visible_report(datetime.now(UTC))
        with self.assertNumQueries(1):
            gate = daily_report_limit_gate(self.team)
        assert gate == DailyReportLimitGate(limited=False, limit=None, reports_today=0)

    @parameterized.expand(
        [
            ("under", 1, 2, False),
            ("at", 2, 2, True),
            ("over", 3, 2, True),
        ]
    )
    def test_gate_compares_todays_count_to_limit(self, _name, visible_today, limit, expected_limited):
        self._set_limit(limit)
        for _ in range(visible_today):
            self._visible_report(datetime.now(UTC))
        gate = daily_report_limit_gate(self.team)
        assert gate == DailyReportLimitGate(limited=expected_limited, limit=limit, reports_today=visible_today)

    def test_only_reports_stamped_today_count(self):
        self._set_limit(1)
        with freeze_time("2026-08-10T12:00:00Z"):
            self._visible_report(datetime(2026, 8, 9, 12, 0, tzinfo=UTC))
            # A pre-migration (or never-surfaced) row has no stamp and must never count.
            self._visible_report(None)
            gate = daily_report_limit_gate(self.team)
        assert gate.reports_today == 0
        assert gate.limited is False

    def test_day_boundary_follows_project_timezone(self):
        # At 05:00 UTC Aug 10 it is 22:00 Aug 9 in Los Angeles, so the local day started at
        # 07:00 UTC Aug 9. A report stamped 08:00 UTC Aug 9 is "today" locally (a UTC boundary
        # would miss it) and one stamped 06:00 UTC Aug 9 (23:00 Aug 8 local) is not.
        self.team.timezone = "America/Los_Angeles"
        self.team.save()
        self._set_limit(1)
        self._visible_report(datetime(2026, 8, 9, 8, 0, tzinfo=UTC))
        self._visible_report(datetime(2026, 8, 9, 6, 0, tzinfo=UTC))
        with freeze_time("2026-08-10T05:00:00Z"):
            # Fresh instance: timezone_info is a cached property on the pre-save one.
            gate = daily_report_limit_gate(Team.objects.get(pk=self.team.pk))
        assert gate.reports_today == 1
        assert gate.limited is True

    def test_limit_lowered_below_todays_count_pauses_immediately(self):
        for _ in range(3):
            self._visible_report(datetime.now(UTC))
        self._set_limit(2)
        assert daily_report_limit_gate(self.team).limited is True

    def test_fails_open_on_count_error(self):
        self._set_limit(1)
        with patch(f"{DAILY_LIMIT_MODULE}.reports_generated_today", side_effect=RuntimeError("db down")):
            gate = daily_report_limit_gate(self.team)
        assert gate == DailyReportLimitGate(limited=False, limit=None, reports_today=0)

    def test_fail_open_metric_noops_outside_activity(self):
        self._set_limit(1)
        with (
            patch(f"{DAILY_LIMIT_MODULE}.reports_generated_today", side_effect=RuntimeError("db down")),
            patch(f"{DAILY_LIMIT_MODULE}.get_metric_meter") as mock_meter,
        ):
            assert daily_report_limit_gate(self.team).limited is False
            mock_meter.assert_not_called()


class TestFirstVisibleStamp(BaseTest):
    @parameterized.expand(
        [
            ("ready", SignalReport.Status.READY, None),
            ("pending_input", SignalReport.Status.PENDING_INPUT, "needs a repository"),
        ]
    )
    def test_first_visible_transition_stamps(self, _name, target, error):
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS)
        updated_fields = report.transition_to(target, title="t", summary="s", error=error)
        assert report.first_visible_at is not None
        assert "first_visible_at" in updated_fields

    def test_stamp_survives_reresearch_and_restore(self):
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS)
        report.transition_to(SignalReport.Status.READY, title="t", summary="s")
        original = report.first_visible_at
        assert original is not None

        # A full re-research cycle a day later must not re-stamp: the report already surfaced
        # once and must not consume the daily limit again.
        report.transition_to(SignalReport.Status.CANDIDATE)
        report.transition_to(SignalReport.Status.IN_PROGRESS, signals_at_run_increment=3)
        with freeze_time(datetime.now(UTC) + timedelta(days=1)):
            updated_fields = report.transition_to(SignalReport.Status.READY, title="t2", summary="s2")
        assert report.first_visible_at == original
        assert "first_visible_at" not in updated_fields

        # Neither must an archive/restore round trip.
        report.transition_to(SignalReport.Status.SUPPRESSED)
        report.transition_to(report.restore_target_status())
        assert report.first_visible_at == original

    @parameterized.expand(
        [
            ("promote", SignalReport.Status.POTENTIAL, SignalReport.Status.CANDIDATE, {}),
            (
                "start_run",
                SignalReport.Status.CANDIDATE,
                SignalReport.Status.IN_PROGRESS,
                {"signals_at_run_increment": 3},
            ),
            ("fail", SignalReport.Status.IN_PROGRESS, SignalReport.Status.FAILED, {"error": "boom"}),
            (
                "reset",
                SignalReport.Status.IN_PROGRESS,
                SignalReport.Status.POTENTIAL,
                {"reset_weight": True},
            ),
        ]
    )
    def test_non_visible_transitions_do_not_stamp(self, _name, start, target, kwargs):
        report = SignalReport.objects.create(team=self.team, status=start)
        report.transition_to(target, **kwargs)
        assert report.first_visible_at is None
