import uuid
from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.artefact_schemas import CheckObservation
from products.signals.backend.models import SignalReport, SignalReportCheck
from products.signals.backend.report_checks import CheckComparison
from products.signals.backend.report_monitoring_summary import MonitoringSummaryState, summarize_monitoring

START = datetime(2026, 11, 1, tzinfo=UTC)


def _report() -> SignalReport:
    return SignalReport(team_id=1, status=SignalReport.Status.MONITORING, monitoring_started_at=START)


def _metric_check(report: SignalReport, *, purpose: str = "expectation", soak_days: int = 7) -> SignalReportCheck:
    return SignalReportCheck(
        id=uuid.uuid4(),
        team_id=1,
        report=report,
        title="Errors stay low",
        kind=SignalReportCheck.Kind.METRIC_THRESHOLD,
        status=SignalReportCheck.Status.ACTIVE,
        config={
            "metric_id": "errors",
            "comparison": {"operator": "lte", "value": 70},
            "baseline_value": 280,
            "monitoring": {
                "purpose": purpose,
                "reference_period_minutes": 10080,
                "threshold_scaling": "linear",
                "baseline_period_minutes": 10080,
            },
        },
        soak_minutes=soak_days * 1440,
        measurement_start_at=START,
        next_run_at=START + timedelta(days=3),
        expires_at=START + timedelta(days=90),
    )


def _agent_check(report: SignalReport) -> SignalReportCheck:
    return SignalReportCheck(
        id=uuid.uuid4(),
        team_id=1,
        report=report,
        title="Agent confirms the fix",
        kind=SignalReportCheck.Kind.AGENT,
        status=SignalReportCheck.Status.ACTIVE,
        config={"instructions": "Look again."},
        soak_minutes=10 * 1440,
        next_run_at=START + timedelta(days=10),
        expires_at=START + timedelta(days=90),
    )


def _reading(
    check: SignalReportCheck, *, day: float, matches: bool | None, started_at: datetime = START
) -> CheckObservation:
    return CheckObservation(
        explanation="",
        check_id=str(check.id),
        title=check.title,
        monitoring_started_at=started_at,
        measured_at=started_at + timedelta(days=day),
        comparison=CheckComparison(operator="lte", value=10 * day) if matches is not None else None,
        observed_value=12.0 if matches is not None else None,
        matches=matches,
        error=None if matches is not None else "query failed",
    )


class TestSummarizeMonitoring(SimpleTestCase):
    @parameterized.expand(
        [
            ("one_off_track_outweighs_on_track", [[True], [True, False]], 2, "not_on_track", 1),
            ("missing_reading_waits", [[True], []], 2, "awaiting_reading", 0),
            ("all_latest_readings_pass", [[False, True], [True]], 2, "on_track", 0),
            ("failed_measurement_keeps_last_verdict", [[True, None]], 2, "on_track", 0),
            ("window_end_outweighs_off_track", [[False]], 8, "window_ended", 0),
        ]
    )
    def test_state_and_lead_check(
        self, _name: str, verdicts: list[list[bool | None]], now_day: int, state: str, lead_index: int
    ) -> None:
        report = _report()
        checks = [_metric_check(report) for _ in verdicts]
        observations = {
            str(check.id): [
                _reading(check, day=index + 1 if matches is not None else 1.5, matches=matches)
                for index, matches in enumerate(check_verdicts)
            ]
            for check, check_verdicts in zip(checks, verdicts)
        }

        summary = summarize_monitoring(
            report, checks, observations, now=START + timedelta(days=now_day), may_read_values=lambda _: True
        )

        assert summary is not None
        assert summary.state == MonitoringSummaryState(state)
        assert summary.lead_check is not None
        assert summary.lead_check.check_id == checks[lead_index].id

    def test_reports_without_interim_readings_wait_for_their_final_checks(self) -> None:
        report = _report()
        guard = _metric_check(report, purpose="minimum_evidence")
        agent = _agent_check(report)

        summary = summarize_monitoring(
            report,
            [guard, agent],
            {str(guard.id): [_reading(guard, day=1, matches=False)]},
            now=START + timedelta(days=2),
            may_read_values=lambda _: True,
        )

        assert summary is not None
        assert summary.state == MonitoringSummaryState.FINAL_CHECK_ONLY
        assert summary.lead_check is None
        assert summary.ends_at == START + timedelta(days=10)

    @parameterized.expand([("readable", True), ("redacted", False)])
    def test_readings_keep_this_period_only_and_hide_values_from_viewers_without_access(
        self, _name: str, readable: bool
    ) -> None:
        report = _report()
        check = _metric_check(report)
        earlier_period = _reading(check, day=1, matches=False, started_at=START - timedelta(days=10))

        summary = summarize_monitoring(
            report,
            [check],
            {
                str(check.id): [
                    _reading(check, day=2, matches=True),
                    earlier_period,
                    _reading(check, day=1, matches=True),
                ]
            },
            now=START + timedelta(days=3),
            may_read_values=lambda _: readable,
        )

        assert summary is not None and summary.lead_check is not None
        lead = summary.lead_check
        assert [reading.measured_at for reading in lead.readings] == [
            START + timedelta(days=1),
            START + timedelta(days=2),
        ]
        assert [reading.threshold for reading in lead.readings] == [10, 20]
        assert [reading.observed_value for reading in lead.readings] == ([12.0, 12.0] if readable else [None, None])
        assert lead.baseline_value == (280 if readable else None)
        assert lead.next_measurement_at == START + timedelta(days=3)
