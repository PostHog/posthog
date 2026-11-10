from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from uuid import UUID

from django.db.models import TextChoices

from pydantic import ValidationError

from posthog.dataclasses import frozen

from products.signals.backend.artefact_schemas import CheckObservation
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportCheck
from products.signals.backend.report_check_monitoring_timing import MonitoringCheckTiming
from products.signals.backend.report_checks import (
    CheckComparison,
    CheckConfigValidationError,
    MetricThresholdConfig,
    MonitoringMetricConfig,
    monitoring_window_end,
    parse_check_config,
)


class MonitoringSummaryState(TextChoices):
    NOT_ON_TRACK = "not_on_track", "Not on track"
    ON_TRACK = "on_track", "On track"
    AWAITING_READING = "awaiting_reading", "Awaiting first reading"
    FINAL_CHECK_ONLY = "final_check_only", "Final check only"
    WINDOW_ENDED = "window_ended", "Window ended"


@frozen
class MonitoringReading:
    measured_at: datetime
    matches: bool | None
    observed_value: float | None
    threshold: float | None


@frozen
class MonitoringLeadCheck:
    check_id: UUID
    title: str
    metric_id: str | None
    metric_kind: str | None
    value_format: str | None
    unit: str | None
    comparison: CheckComparison
    monitoring: MonitoringMetricConfig
    baseline_value: float | None
    ends_at: datetime
    next_measurement_at: datetime | None
    readings: tuple[MonitoringReading, ...]


@frozen
class ReportMonitoringSummary:
    state: MonitoringSummaryState
    started_at: datetime
    ends_at: datetime
    lead_check: MonitoringLeadCheck | None


@frozen
class _OpenCheck:
    check: SignalReportCheck
    config: MetricThresholdConfig | None
    ends_at: datetime
    readings: tuple[MonitoringReading, ...]

    @property
    def is_expectation(self) -> bool:
        return (
            self.config is not None
            and self.config.monitoring is not None
            and self.config.monitoring.purpose == "expectation"
        )

    @property
    def latest_verdict(self) -> bool | None:
        return next((reading.matches for reading in reversed(self.readings) if reading.matches is not None), None)


def _metric_config(check: SignalReportCheck) -> MetricThresholdConfig | None:
    if check.kind != SignalReportCheck.Kind.METRIC_THRESHOLD:
        return None
    try:
        config = parse_check_config(check.kind, check.config)
    except CheckConfigValidationError:
        return None
    return config if isinstance(config, MetricThresholdConfig) else None


def _observations_by_check(
    reports: Mapping[UUID, SignalReport], *, team_id: int, since: datetime
) -> defaultdict[str, list[CheckObservation]]:
    rows = SignalReportArtefact.objects.filter(
        team_id=team_id,
        report_id__in=reports.keys(),
        type=SignalReportArtefact.ArtefactType.CHECK_OBSERVATION,
        created_at__gte=since,
    ).values_list("content", flat=True)
    observations: defaultdict[str, list[CheckObservation]] = defaultdict(list)
    for content in rows:
        try:
            observation = CheckObservation.model_validate_json(content)
        except ValidationError:
            continue
        observations[observation.check_id].append(observation)
    return observations


def monitoring_summaries(
    reports: Sequence[SignalReport],
    *,
    team_id: int,
    now: datetime,
    may_read_values: Callable[[Mapping[str, object]], bool],
) -> dict[str, ReportMonitoringSummary]:
    """Summarize each Monitoring report on a list page for its row, in two queries for the whole page."""
    monitored = {
        report.id: report
        for report in reports
        if report.status == SignalReport.Status.MONITORING and report.monitoring_started_at is not None
    }
    if not monitored:
        return {}
    checks_by_report: defaultdict[UUID, list[SignalReportCheck]] = defaultdict(list)
    for check in (
        SignalReportCheck.objects.for_team(team_id)
        .filter(report_id__in=monitored.keys(), status__in=SignalReportCheck.OPEN_STATUSES)
        .defer("rationale")
        .order_by("created_at", "id")
    ):
        check.report = monitored[check.report_id]
        checks_by_report[check.report_id].append(check)
    observations = _observations_by_check(
        monitored,
        team_id=team_id,
        since=min(report.monitoring_started_at for report in monitored.values() if report.monitoring_started_at),
    )
    summaries: dict[str, ReportMonitoringSummary] = {}
    for report_id, checks in checks_by_report.items():
        summary = summarize_monitoring(
            monitored[report_id],
            checks,
            {str(check.id): observations.get(str(check.id), []) for check in checks},
            now=now,
            may_read_values=may_read_values,
        )
        if summary is not None:
            summaries[str(report_id)] = summary
    return summaries


def summarize_monitoring(
    report: SignalReport,
    checks: Sequence[SignalReportCheck],
    observations: Mapping[str, Sequence[CheckObservation]],
    *,
    now: datetime,
    may_read_values: Callable[[Mapping[str, object]], bool],
) -> ReportMonitoringSummary | None:
    """Roll a Monitoring report's open checks and interim readings up into what its inbox row shows.

    `may_read_values` gates measured numbers the way a check result is gated: a viewer who may not read
    the check's data keeps the verdicts and the target, but not the observed values or the baseline.
    """
    started_at = report.monitoring_started_at
    if started_at is None:
        return None
    members: list[_OpenCheck] = []
    for check in checks:
        if check.is_terminal or check.expires_at <= now or check.soak_minutes is None:
            continue
        config = _metric_config(check)
        readable = config is not None and may_read_values(check.config)
        readings = tuple(
            MonitoringReading(
                measured_at=observation.measured_at,
                matches=observation.matches,
                observed_value=observation.observed_value if readable else None,
                threshold=observation.comparison.value if observation.comparison else None,
            )
            for observation in sorted(observations.get(str(check.id), ()), key=lambda o: o.measured_at)
            # A restarted Monitoring period keeps the earlier period's observations on the report.
            if observation.monitoring_started_at == started_at
        )
        members.append(
            _OpenCheck(
                check=check,
                config=config,
                ends_at=monitoring_window_end(started_at, check.soak_minutes),
                readings=readings,
            )
        )
    if not members:
        return None

    ends_at = max(member.ends_at for member in members)
    expectations = [member for member in members if member.is_expectation]
    off_track = [member for member in expectations if member.latest_verdict is False]
    if now >= ends_at:
        state = MonitoringSummaryState.WINDOW_ENDED
    elif off_track:
        state = MonitoringSummaryState.NOT_ON_TRACK
    elif any(member.latest_verdict is None for member in expectations):
        state = MonitoringSummaryState.AWAITING_READING
    elif expectations:
        state = MonitoringSummaryState.ON_TRACK
    else:
        state = MonitoringSummaryState.FINAL_CHECK_ONLY
    lead = off_track[0] if off_track else (expectations[0] if expectations else None)
    return ReportMonitoringSummary(
        state=state,
        started_at=started_at,
        ends_at=ends_at,
        lead_check=_lead_check(lead, now=now, may_read_values=may_read_values) if lead else None,
    )


def _lead_check(
    member: _OpenCheck, *, now: datetime, may_read_values: Callable[[Mapping[str, object]], bool]
) -> MonitoringLeadCheck:
    config = member.config
    assert config is not None and config.monitoring is not None
    timing = MonitoringCheckTiming.for_check(member.check, now=now)
    return MonitoringLeadCheck(
        check_id=member.check.id,
        title=member.check.title,
        metric_id=config.metric_id,
        metric_kind=config.metric_kind,
        value_format=config.value_format,
        unit=config.unit,
        comparison=config.comparison,
        monitoring=config.monitoring,
        baseline_value=config.baseline_value if may_read_values(member.check.config) else None,
        ends_at=member.ends_at,
        next_measurement_at=timing.next_measurement_at if timing else None,
        readings=member.readings,
    )
