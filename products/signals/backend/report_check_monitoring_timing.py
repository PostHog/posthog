from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from django.db.models import TextChoices

from posthog.dataclasses import frozen

from products.signals.backend.report_checks import MAX_CHECK_HORIZON, monitoring_window_end

if TYPE_CHECKING:
    from products.signals.backend.models import SignalReportCheck


class MonitoringCheckTimingState(TextChoices):
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
    def for_check(cls, check: SignalReportCheck, *, now: datetime) -> MonitoringCheckTiming | None:
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
