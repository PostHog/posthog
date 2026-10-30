from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import TextChoices

from posthog.dataclasses import frozen

from products.signals.backend.models import SignalReportMonitoringResult, SignalScoutRun
from products.signals.backend.report_check_final_agents import MonitoringScoutCheck, _monitoring_binding_for_run
from products.signals.backend.report_checks import MAX_CHECK_HORIZON, monitoring_window_end
from products.signals.backend.report_monitoring_attempts import check_definition_version, current_monitoring_attempt
from products.signals.backend.report_monitoring_results import InvalidMonitoringResult
from products.signals.backend.scout_harness.limits import STALE_RUN_CUTOFF_S, TRIGGERED_BY_MONITORING

if TYPE_CHECKING:
    from products.signals.backend.models import SignalReport, SignalReportCheck


class MonitoringCheckTimingState(TextChoices):
    MONITORING = "monitoring", "Monitoring"
    VERIFYING = "verifying", "Verifying"
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
class MonitoringCheckTiming:
    state: MonitoringCheckTimingState
    started_at: datetime | None
    ends_at: datetime | None
    next_measurement_at: datetime | None = None

    @classmethod
    def running_verifications(cls, report: SignalReport, *, now: datetime) -> dict[UUID, MonitoringScoutCheck]:
        attempt = current_monitoring_attempt(report)
        if attempt is None:
            return {}
        submitted = SignalReportMonitoringResult.objects.for_team(report.team_id).filter(attempt_id=attempt.id)
        submitted_ids = set(submitted.values_list("submission_id", flat=True))
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
        return running

    @staticmethod
    def _agent_state(
        check: SignalReportCheck,
        *,
        now: datetime,
        start: datetime,
        end: datetime,
        verification: MonitoringScoutCheck | None,
    ) -> MonitoringCheckTimingState:
        if now < end:
            return MonitoringCheckTimingState.MONITORING
        if (
            verification is not None
            and verification.check_id == check.id
            and verification.window_start == start
            and verification.window_end == end
            and verification.definition_version == check_definition_version(check)
        ):
            return MonitoringCheckTimingState.VERIFYING
        return MonitoringCheckTimingState.WINDOW_ENDED

    @classmethod
    def for_check(
        cls, check: SignalReportCheck, *, now: datetime, verification: MonitoringScoutCheck | None = None
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
            state = cls._agent_state(check, now=now, start=start, end=end, verification=verification)
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
