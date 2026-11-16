from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from uuid import UUID

from django.db.models import TextChoices

from pydantic import ValidationError

from posthog.dataclasses import frozen

from products.signals.backend.artefact_schemas import CheckObservation
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportCheck,
    SignalReportMonitoringAttempt,
)
from products.signals.backend.report_check_monitoring_timing import MonitoringCheckTiming, MonitoringCheckTimingState
from products.signals.backend.report_checks import (
    CheckComparison,
    CheckConfigValidationError,
    MetricThresholdConfig,
    MonitoringMetricConfig,
    monitoring_window_end,
    parse_check_config,
)
from products.signals.backend.report_monitoring_attempts import check_definition_version


class MonitoringSummaryState(TextChoices):
    NOT_ON_TRACK = "not_on_track", "Not on track"
    ON_TRACK = "on_track", "On track"
    AWAITING_READING = "awaiting_reading", "Awaiting first reading"
    READINGS_HIDDEN = "readings_hidden", "Readings hidden"
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


_READING_DUE_STATES = frozenset(
    {MonitoringCheckTimingState.SCHEDULED, MonitoringCheckTimingState.DUE, MonitoringCheckTimingState.WAITING}
)


@frozen
class _OpenCheck:
    check: SignalReportCheck
    config: MetricThresholdConfig | None
    ends_at: datetime
    readings: tuple[MonitoringReading, ...]
    readable: bool
    timing: MonitoringCheckTiming | None

    @property
    def takes_interim_readings(self) -> bool:
        """An expectation check that has an interim reading, or still has one coming.

        A soak no longer than the measurement cadence schedules its first run at the window end, so
        its outcome waits for the final check like an agent's does.
        """
        return (
            self.config is not None
            and self.config.monitoring is not None
            and self.config.monitoring.purpose == "expectation"
            and (
                self.final_verdict is not None
                or bool(self.readings)
                or (self.timing is not None and self.timing.state in _READING_DUE_STATES)
            )
        )

    @property
    def final_verdict(self) -> bool | None:
        """The verdict final verification recorded on the check. It outranks any interim reading before it."""
        if self.check.status == SignalReportCheck.Status.PASSED:
            return True
        if self.check.status == SignalReportCheck.Status.FAILED:
            return False
        return None

    @property
    def is_visible(self) -> bool:
        # A final pass or fail is on the check row every reader already sees; interim readings are not.
        return self.readable or self.final_verdict is not None

    @property
    def latest_verdict(self) -> bool | None:
        if self.final_verdict is not None:
            return self.final_verdict
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
    """Summarize each Monitoring report on a list page for its row, in three queries for the whole page."""
    monitored = {
        report.id: report
        for report in reports
        if report.status == SignalReport.Status.MONITORING and report.monitoring_started_at is not None
    }
    if not monitored:
        return {}
    attempts = {
        attempt.report_id: attempt
        for attempt in SignalReportMonitoringAttempt.objects.for_team(team_id).filter(report_id__in=monitored.keys())
        if attempt.monitoring_started_at == monitored[attempt.report_id].monitoring_started_at
    }
    checks_by_report: defaultdict[UUID, list[SignalReportCheck]] = defaultdict(list)
    for check in (
        SignalReportCheck.objects.for_team(team_id)
        .filter(
            report_id__in=attempts.keys(),
            id__in=[check_id for attempt in attempts.values() for check_id in attempt.check_versions],
        )
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
            check_versions=attempts[report_id].check_versions,
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
    check_versions: Mapping[str, str],
    now: datetime,
    may_read_values: Callable[[Mapping[str, object]], bool],
) -> ReportMonitoringSummary | None:
    """Roll a Monitoring report's open checks and interim readings up into what its inbox row shows.

    `may_read_values` gates readings the way the report's artefacts gate a check observation: a viewer
    who may not read a check's data sees when it was measured, but not the value, the threshold, or
    whether it matched, and no state derived from them.

    Only the attempt's snapshot members count, whatever their status, because those are the checks
    final verification decides the attempt with. A member whose definition changed since the snapshot
    keeps its window but contributes no readings, since final verification will not accept them either.
    """
    started_at = report.monitoring_started_at
    if started_at is None:
        return None
    members: list[_OpenCheck] = []
    for check in checks:
        snapshot_version = check_versions.get(str(check.id))
        if snapshot_version is None or check.soak_minutes is None:
            continue
        current = check_definition_version(check) == snapshot_version
        config = _metric_config(check)
        readable = config is not None and may_read_values(check.config)
        readings = tuple(
            MonitoringReading(
                measured_at=observation.measured_at,
                matches=observation.matches if readable else None,
                observed_value=observation.observed_value if readable else None,
                threshold=observation.comparison.value if readable and observation.comparison else None,
            )
            for observation in sorted(
                observations.get(str(check.id), ()) if current else (), key=lambda o: o.measured_at
            )
            # A restarted Monitoring period keeps the earlier period's observations on the report.
            if observation.monitoring_started_at == started_at
        )
        members.append(
            _OpenCheck(
                check=check,
                config=config,
                ends_at=monitoring_window_end(started_at, check.soak_minutes),
                readings=readings,
                readable=readable,
                timing=MonitoringCheckTiming.for_check(check, now=now) if config is not None else None,
            )
        )
    if not members:
        return None

    ends_at = max(member.ends_at for member in members)
    interim = [member for member in members if member.takes_interim_readings]
    visible = [member for member in interim if member.is_visible]
    off_track = [member for member in visible if member.latest_verdict is False]
    if now >= ends_at:
        state = MonitoringSummaryState.WINDOW_ENDED
    elif off_track:
        state = MonitoringSummaryState.NOT_ON_TRACK
    elif any(member.latest_verdict is None for member in visible):
        state = MonitoringSummaryState.AWAITING_READING
    elif len(visible) < len(interim):
        state = MonitoringSummaryState.READINGS_HIDDEN
    elif interim:
        state = MonitoringSummaryState.ON_TRACK
    else:
        state = MonitoringSummaryState.FINAL_CHECK_ONLY
    lead = off_track[0] if off_track else (interim[0] if interim else None)
    return ReportMonitoringSummary(
        state=state,
        started_at=started_at,
        ends_at=ends_at,
        lead_check=_lead_check(lead, report) if lead else None,
    )


def _lead_check(member: _OpenCheck, report: SignalReport) -> MonitoringLeadCheck:
    config = member.config
    assert config is not None and config.monitoring is not None
    # A report can rewrite its metric under the same id while the check keeps measuring the query it
    # was created with, so the row may only draw the report metric that still runs that query.
    measures_report_metric = any(
        isinstance(metric, Mapping)
        and metric.get("metric_id") == config.metric_id
        and metric.get("query") == member.check.config.get("query")
        for metric in report.metrics or []
    )
    return MonitoringLeadCheck(
        check_id=member.check.id,
        title=member.check.title,
        metric_id=config.metric_id if measures_report_metric else None,
        metric_kind=config.metric_kind,
        value_format=config.value_format,
        unit=config.unit,
        comparison=config.comparison,
        monitoring=config.monitoring,
        baseline_value=config.baseline_value if member.readable else None,
        ends_at=member.ends_at,
        next_measurement_at=member.timing.next_measurement_at if member.timing else None,
        readings=member.readings,
    )
