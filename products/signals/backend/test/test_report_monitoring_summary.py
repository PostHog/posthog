import uuid
from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.artefact_schemas import CheckObservation
from products.signals.backend.models import SignalReport, SignalReportCheck
from products.signals.backend.report_checks import CheckComparison
from products.signals.backend.report_monitoring_attempts import check_definition_version
from products.signals.backend.report_monitoring_summary import (
    MonitoringSummaryState,
    ReportMonitoringSummary,
    summarize_monitoring,
)

START = datetime(2026, 11, 1, tzinfo=UTC)


def _report() -> SignalReport:
    return SignalReport(team_id=1, status=SignalReport.Status.MONITORING, monitoring_started_at=START)


def _metric_check(
    report: SignalReport,
    *,
    purpose: str = "expectation",
    soak: timedelta = timedelta(days=7),
    next_run_at: datetime = START + timedelta(days=3),
) -> SignalReportCheck:
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
        soak_minutes=int(soak.total_seconds() // 60),
        measurement_start_at=START,
        next_run_at=next_run_at,
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


def _summarize(
    report: SignalReport,
    checks: list[SignalReportCheck],
    observations: dict[str, list[CheckObservation]],
    *,
    now: datetime,
    readable: bool = True,
    members: list[SignalReportCheck] | None = None,
) -> ReportMonitoringSummary | None:
    return summarize_monitoring(
        report,
        checks,
        observations,
        check_versions={str(check.id): check_definition_version(check) for check in members or checks},
        now=now,
        may_read_values=lambda _: readable,
    )


class TestSummarizeMonitoring(SimpleTestCase):
    @parameterized.expand(
        [
            ("one_off_track_outweighs_on_track", [[True], [True, False]], 2, "not_on_track", 1),
            ("missing_reading_waits", [[True], []], 2, "awaiting_reading", 0),
            ("all_latest_readings_pass", [[False, True], [True]], 2, "on_track", 0),
            ("failed_measurement_keeps_last_verdict", [[True, None]], 2, "on_track", 0),
            ("window_end_outweighs_off_track", [[False]], 8, "window_ended", 0),
            # Final verification still decides with an errored member, so its readings still count.
            ("errored_member_still_counts", [[True], [False]], 2, "not_on_track", 1, "errored"),
            # A passed final verdict outranks the interim miss before it.
            ("final_pass_outranks_interim_failure", [[True], [False]], 2, "on_track", 0, "passed"),
        ]
    )
    def test_state_and_lead_check(
        self,
        _name: str,
        verdicts: list[list[bool | None]],
        now_day: int,
        state: str,
        lead_index: int,
        last_status: str | None = None,
    ) -> None:
        report = _report()
        checks = [_metric_check(report) for _ in verdicts]
        if last_status is not None:
            checks[-1].status = last_status
        observations = {
            str(check.id): [
                _reading(check, day=index + 1 if matches is not None else 1.5, matches=matches)
                for index, matches in enumerate(check_verdicts)
            ]
            for check, check_verdicts in zip(checks, verdicts)
        }

        summary = _summarize(report, checks, observations, now=START + timedelta(days=now_day))

        assert summary is not None
        assert summary.state == MonitoringSummaryState(state)
        assert summary.lead_check is not None
        assert summary.lead_check.check_id == checks[lead_index].id

    @parameterized.expand([("before_the_short_window_ends", 1), ("after_the_short_window_ends", 48)])
    def test_reports_without_interim_readings_wait_for_their_final_checks(self, _name: str, now_hours: int) -> None:
        report = _report()
        guard = _metric_check(report, purpose="minimum_evidence")
        # A soak no longer than the cadence takes its only measurement at the window end.
        short = _metric_check(report, soak=timedelta(hours=6), next_run_at=START + timedelta(hours=6))
        agent = _agent_check(report)
        # Written after Monitoring began, so it is outside the attempt and cannot extend the window.
        late = _agent_check(report)
        late.soak_minutes = 20 * 1440

        summary = _summarize(
            report,
            [guard, short, agent, late],
            {str(guard.id): [_reading(guard, day=1, matches=False)]},
            now=START + timedelta(hours=now_hours),
            members=[guard, short, agent],
        )

        assert summary is not None
        assert summary.state == MonitoringSummaryState.FINAL_CHECK_ONLY
        assert summary.lead_check is None
        assert summary.ends_at == START + timedelta(days=10)

    @parameterized.expand([("readable", True, "not_on_track"), ("redacted", False, "readings_hidden")])
    def test_readings_keep_this_period_only_and_hide_verdicts_from_viewers_without_access(
        self, _name: str, readable: bool, state: str
    ) -> None:
        report = _report()
        check = _metric_check(report)
        earlier_period = _reading(check, day=1, matches=False, started_at=START - timedelta(days=10))

        summary = _summarize(
            report,
            [check],
            {
                str(check.id): [
                    _reading(check, day=2, matches=False),
                    earlier_period,
                    _reading(check, day=1, matches=True),
                ]
            },
            now=START + timedelta(days=3),
            readable=readable,
        )

        assert summary is not None and summary.lead_check is not None
        assert summary.state == MonitoringSummaryState(state)
        lead = summary.lead_check
        assert [reading.measured_at for reading in lead.readings] == [
            START + timedelta(days=1),
            START + timedelta(days=2),
        ]
        assert [reading.matches for reading in lead.readings] == ([True, False] if readable else [None, None])
        assert [reading.threshold for reading in lead.readings] == ([10, 20] if readable else [None, None])
        assert [reading.observed_value for reading in lead.readings] == ([12.0, 12.0] if readable else [None, None])
        assert lead.baseline_value == (280 if readable else None)
        assert lead.next_measurement_at == START + timedelta(days=3)

    @parameterized.expand([("same_query", None, "errors"), ("rewritten", {"kind": "InsightVizNode"}, None)])
    def test_lead_check_names_the_report_metric_only_while_it_runs_the_checks_query(
        self, _name: str, report_query: dict | None, metric_id: str | None
    ) -> None:
        report = _report()
        report.metrics = [{"metric_id": "errors", "query": report_query}]
        check = _metric_check(report)

        summary = _summarize(report, [check], {}, now=START + timedelta(days=1))

        assert summary is not None and summary.lead_check is not None
        assert summary.lead_check.metric_id == metric_id
