from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import TextChoices

from posthog.dataclasses import frozen

from products.signals.backend.models import SignalReportMonitoringResult, SignalScoutRun
from products.signals.backend.report_check_final_agents import MonitoringScoutCheck, _monitoring_binding_for_run
from products.signals.backend.report_checks import MAX_CHECK_HORIZON, monitoring_window_end
from products.signals.backend.report_monitoring_aggregation import MonitoringMemberState
from products.signals.backend.report_monitoring_attempts import check_definition_version
from products.signals.backend.report_monitoring_outcomes import _member_results, _member_state
from products.signals.backend.report_monitoring_results import InvalidMonitoringResult
from products.signals.backend.scout_harness.limits import STALE_RUN_CUTOFF_S, TRIGGERED_BY_MONITORING

if TYPE_CHECKING:
    from products.signals.backend.models import SignalReport, SignalReportCheck, SignalReportMonitoringAttempt


class MonitoringCheckTimingState(TextChoices):
    MONITORING = "monitoring", "Monitoring"
    VERIFYING = "verifying", "Verifying"
    ASSESSMENT_REQUIRED = "assessment_required", "Assessment required"
    VERIFICATION_COMPLETE = "verification_complete", "Verification complete"
    SCHEDULED = "scheduled", "Scheduled"
    DUE = "due", "Due"
    WINDOW_ENDED = "window_ended", "Window ended"
    NO_INTERIM_MEASUREMENTS = "no_interim_measurements", "No interim measurements"
    WAITING = "waiting", "Waiting for scheduling"
    PAUSED = "paused", "Paused during Monitoring"
    ARCHIVED = "archived", "Archived"
    UNAVAILABLE = "unavailable", "Timing unavailable"
    EXPIRY_REACHED = "expiry_reached", "Expiry reached"


@frozen
class MonitoringCheckVerification:
    run: MonitoringScoutCheck | None = None
    results: tuple[SignalReportMonitoringResult, ...] = ()


@frozen
class MonitoringCheckTiming:
    state: MonitoringCheckTimingState
    started_at: datetime | None
    ends_at: datetime | None
    next_measurement_at: datetime | None = None

    @classmethod
    def final_verifications(
        cls, report: SignalReport, *, now: datetime, attempt: SignalReportMonitoringAttempt
    ) -> dict[UUID, MonitoringCheckVerification]:
        submitted = list(
            SignalReportMonitoringResult.objects.for_team(report.team_id)
            .filter(attempt_id=attempt.id)
            .only(
                "report_check_id",
                "submission_id",
                "definition_version",
                "window_start",
                "window_end",
                "evaluated_at",
                "evidence_status",
                "outcome",
                "expectation_matches",
            )
        )
        submitted_ids = {result.submission_id for result in submitted}
        results_by_check: defaultdict[UUID, list[SignalReportMonitoringResult]] = defaultdict(list)
        for result in submitted:
            results_by_check[result.report_check_id].append(result)
        runs = (
            SignalScoutRun.objects.for_team(report.team_id)
            .only("team_id", "metadata")
            .filter(
                metadata__triggered_by=TRIGGERED_BY_MONITORING,
                metadata__run_note__icontains=str(report.id),
                task_run__status="in_progress",
                task_run__team_id=report.team_id,
                created_at__gt=now - timedelta(seconds=STALE_RUN_CUTOFF_S),
            )
        )
        running: dict[UUID, MonitoringScoutCheck] = {}
        for run in runs:
            try:
                binding = _monitoring_binding_for_run(run)
            except InvalidMonitoringResult:
                continue
            if (
                binding.report_id == report.id
                and binding.attempt_id == attempt.id
                and binding.window_start == attempt.monitoring_started_at
                and attempt.check_versions.get(str(binding.check_id)) == binding.definition_version
                and binding.submission_id not in submitted_ids
            ):
                running[binding.check_id] = binding
        return {
            check_id: MonitoringCheckVerification(run=running.get(check_id), results=tuple(results_by_check[check_id]))
            for check_id in running.keys() | results_by_check.keys()
        }

    @staticmethod
    def _agent_state(
        check: SignalReportCheck,
        *,
        now: datetime,
        start: datetime,
        end: datetime,
        attempt: SignalReportMonitoringAttempt | None,
        verification: MonitoringCheckVerification | None,
    ) -> MonitoringCheckTimingState:
        version = check_definition_version(check)
        if (
            attempt is None
            or attempt.report_id != check.report_id
            or attempt.monitoring_started_at != start
            or attempt.check_versions.get(str(check.id)) != version
            or check.report.team.parent_team_id is not None
        ):
            return MonitoringCheckTimingState.PAUSED
        if now < end:
            return MonitoringCheckTimingState.MONITORING
        if verification is None:
            return MonitoringCheckTimingState.WINDOW_ENDED
        state = _member_state(_member_results(check, version, attempt, list(verification.results), now))
        if state in {MonitoringMemberState.INCONCLUSIVE, MonitoringMemberState.EXHAUSTED}:
            return MonitoringCheckTimingState.ASSESSMENT_REQUIRED
        if state in {MonitoringMemberState.PASSED, MonitoringMemberState.FAILED}:
            return MonitoringCheckTimingState.VERIFICATION_COMPLETE
        run = verification.run
        if (
            run is not None
            and run.check_id == check.id
            and run.window_start == start
            and run.window_end == end
            and run.definition_version == version
        ):
            return MonitoringCheckTimingState.VERIFYING
        return MonitoringCheckTimingState.WINDOW_ENDED

    @classmethod
    def for_check(
        cls,
        check: SignalReportCheck,
        *,
        now: datetime,
        attempt: SignalReportMonitoringAttempt | None = None,
        verification: MonitoringCheckVerification | None = None,
    ) -> MonitoringCheckTiming | None:
        report = check.report
        archived = (
            report.status == report.Status.SUPPRESSED and report.status_before_suppression == report.Status.MONITORING
        )
        if check.is_terminal or (report.status != report.Status.MONITORING and not archived):
            return None

        start = report.monitoring_started_at
        end = (
            monitoring_window_end(start, check.soak_minutes)
            if start is not None and check.soak_minutes is not None
            else None
        )
        if archived:
            state = MonitoringCheckTimingState.ARCHIVED
        elif start is None or end is None:
            state = MonitoringCheckTimingState.UNAVAILABLE
        elif check.kind == check.Kind.AGENT:
            state = cls._agent_state(check, now=now, start=start, end=end, attempt=attempt, verification=verification)
        elif check.expires_at <= now or now >= start + MAX_CHECK_HORIZON:
            state = MonitoringCheckTimingState.EXPIRY_REACHED
        elif check.kind != check.Kind.METRIC_THRESHOLD or not check.config.get("monitoring"):
            state = MonitoringCheckTimingState.PAUSED
        elif now >= end:
            state = MonitoringCheckTimingState.WINDOW_ENDED
        elif check.status == check.Status.PENDING or check.measurement_start_at != start:
            state = MonitoringCheckTimingState.WAITING
        elif check.next_run_at >= min(end, check.expires_at):
            state = MonitoringCheckTimingState.NO_INTERIM_MEASUREMENTS
        else:
            return cls(
                state=MonitoringCheckTimingState.DUE
                if check.next_run_at <= now
                else MonitoringCheckTimingState.SCHEDULED,
                started_at=start,
                ends_at=end,
                next_measurement_at=check.next_run_at,
            )
        return cls(state=state, started_at=start, ends_at=end)
