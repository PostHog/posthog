"""Coordinate interim check measurements during enabled Monitoring.

Final verification and authored agent checks use separate execution contracts. The legacy verdict
utilities below do not run from the coordinator.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from datetime import datetime, timedelta
from functools import partial
from typing import cast
from uuid import UUID

from django.db import transaction
from django.db.models import (
    Case,
    DateTimeField,
    DurationField,
    Exists,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    Value,
    When,
    Window,
)
from django.db.models.functions import Coalesce, Greatest, Least, RowNumber
from django.utils import timezone

import structlog

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import CheckResult
from products.signals.backend.enums import SignalSourceProduct, SignalSourceType
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportCheck
from products.signals.backend.report_check_artefacts import write_check_expired
from products.signals.backend.report_check_evaluation import (
    CheckVerdict,
    describe_comparison,
    errored_check_explanation,
    evaluate_check_value,
)
from products.signals.backend.report_check_monitoring import (
    MonitoringWindowClosed,
    measure_monitoring_check,
    record_monitoring_observation,
)
from products.signals.backend.report_check_telemetry import (
    capture_report_check_evaluated,
    capture_report_checks_expired,
)
from products.signals.backend.report_check_timing import metric_check_ready_at, metric_check_window_start
from products.signals.backend.report_checks import (
    AWAITING_DATA_RETRY_WAITS,
    DEFAULT_CHECK_SOAK_HOURS,
    DEFAULT_MONITORING_INTERVAL_MINUTES,
    MAX_CHECK_HORIZON,
    MAX_CONSECUTIVE_CHECK_ERRORS,
    MIN_CHECK_INTERVAL_MINUTES,
    CheckConfigValidationError,
    MetricThresholdConfig,
    check_schedule_expires_at,
    parse_check_config,
    soak_minutes_from_gap,
)
from products.signals.backend.report_content_gates import team_report_monitoring_enabled
from products.signals.backend.report_lifecycle import check_monitoring_disabled_organizations, report_status_filter
from products.signals.backend.report_metric_refresh import MetricQueryBudgetExhausted, measure_metric
from products.signals.backend.report_metrics import validate_live_metric_query

logger = structlog.get_logger(__name__)

# Per-tick cost ceiling. A check is one cached Trends query, so this is generous — the per-team cap
# below is what keeps one busy team from filling the tick.
MAX_CHECK_RUNS_PER_TICK = 50
MAX_CHECK_RUNS_PER_TEAM_PER_TICK = 10
CHECK_RUN_TIME_BUDGET_SECONDS = 120.0
# Rows swept per tick when their horizon passed without a run. Bounded so a backlog costs one
# bounded UPDATE rather than a table-wide one.
MAX_CHECK_EXPIRIES_PER_TICK = 500
# An errored run retries on the next window instead of retiring the check, so a transient query
# failure does not end a soak. It does not consume `runs_remaining`.
CHECK_ERROR_RETRY_AFTER = timedelta(hours=6)
# Weight of the signal a failed check on a resolved report emits. High enough to promote on its own:
# a fix that stopped holding is a finding somebody already decided was worth fixing once.
CHECK_FAILURE_SIGNAL_WEIGHT = 1.0

# Rows moved back to `pending` per tick because their report is not resolved. Bounded the same way.
MAX_CHECK_PARKS_PER_TICK = 500


@frozen
class CheckRunSummary:
    expired: int
    passed: int
    failed: int
    errored: int
    inconclusive: int = 0
    observed: int = 0
    # An `agent` check the tick started a scout run for, and one the fleet could not take yet.
    # Neither is an outcome: both rows are still active and still owe a verdict.
    dispatched: int = 0
    deferred: int = 0
    # An `agent` check stopped because its project has no scout to run it.
    cancelled: int = 0


@frozen
class _CheckTransition:
    """Where a check goes after one verdict. `next_run_at` is None when the check retires."""

    status: str
    next_run_at: datetime | None
    runs_remaining: int


def resolve_check_query(config: MetricThresholdConfig, report: SignalReport) -> dict:
    """The query this check measures: the one stored on it, else the report metric it names.

    The create path copies a named metric's query onto the check, so the fallback only serves rows
    written another way. Such a row is re-validated here, the way the metric refresh re-validates
    before it measures: `report.metrics` is plain JSON that can change after the check was written,
    and the runner reads one series out of the result, so a row carrying a breakdown or several
    output series would turn an arbitrary slice into a recorded verdict.
    """

    if config.query is not None:
        return config.query
    for row in report.metrics or []:
        if isinstance(row, dict) and row.get("metric_id") == config.metric_id and isinstance(row.get("query"), dict):
            try:
                return validate_live_metric_query(row["query"])
            except ValueError as error:
                raise ValueError(
                    f"metric `{config.metric_id}` no longer measures one bounded number: {error}"
                ) from None
    raise ValueError(f"the report has no metric `{config.metric_id}` to measure")


def measure_check(check: SignalReportCheck, *, deadline: float) -> CheckVerdict:
    """Run one check and return its verdict. Never raises: a failure to measure is an `errored` verdict."""

    try:
        config = parse_check_config(check.kind, check.config)
        assert isinstance(config, MetricThresholdConfig)
        query = resolve_check_query(config, check.report)
        if check.measurement_start_at is not None:
            now = timezone.now()
            window_start = metric_check_window_start(query, check.report.team, now)
            if window_start < check.measurement_start_at:
                return CheckVerdict(
                    outcome="inconclusive", reason="awaiting_data", explanation="Waiting for a full measurement window."
                )
            # Pin this run's bounds so a cached relative query cannot include pre-resolution data.
            query = {
                **query,
                "source": {
                    **query["source"],
                    "dateRange": {
                        **query["source"]["dateRange"],
                        "date_from": window_start.isoformat(),
                        "date_to": now.isoformat(),
                        "explicitDate": True,
                    },
                },
            }
        tag_queries(trigger="signals_report_check")
        measurement = measure_metric(
            query, check.report.team, deadline=deadline, include_series=False, ch_user=ClickHouseUser.SIGNALS
        )
    except Exception as error:
        logger.exception("signals.report_check.measurement_failed", check_id=str(check.id), team_id=check.team_id)
        return CheckVerdict(outcome="errored", explanation=errored_check_explanation(error, subject=check.title))
    return evaluate_check_value(comparison=config.comparison, observed_value=measurement.value, subject=check.title)


def _next_state(check: SignalReportCheck, verdict: CheckVerdict, now: datetime) -> _CheckTransition:
    """The check's status after this verdict, its next run time, and its remaining runs.

    Re-arming anchors on `now` rather than the missed slot, so a coordinator outage cannot leave a
    recurring check owing a burst of catch-up runs.

    An `inconclusive` verdict never counts toward `MAX_CONSECUTIVE_CHECK_ERRORS`, because the run
    worked. Only `awaiting_data` keeps the check open. It retires as `inconclusive` when its retries
    run out or the next look would fall past the horizon, so a check that said why on every run does
    not end as a silent `expired`.
    """
    if verdict.outcome == "failed":
        return _CheckTransition(
            status=SignalReportCheck.Status.FAILED, next_run_at=None, runs_remaining=check.runs_remaining
        )

    if verdict.outcome == "errored":
        if check.consecutive_errors + 1 >= MAX_CONSECUTIVE_CHECK_ERRORS:
            return _CheckTransition(
                status=SignalReportCheck.Status.ERRORED, next_run_at=None, runs_remaining=check.runs_remaining
            )
        retry_at = now + CHECK_ERROR_RETRY_AFTER
        if retry_at > check.expires_at:
            return _CheckTransition(
                status=SignalReportCheck.Status.EXPIRED, next_run_at=None, runs_remaining=check.runs_remaining
            )
        return _CheckTransition(
            status=SignalReportCheck.Status.ACTIVE, next_run_at=retry_at, runs_remaining=check.runs_remaining
        )

    if verdict.outcome == "inconclusive":
        retries = check.consecutive_inconclusive
        can_wait = verdict.reason == "awaiting_data" and retries < len(AWAITING_DATA_RETRY_WAITS)
        next_look_at = now + AWAITING_DATA_RETRY_WAITS[retries] if can_wait else None
        # `>=`, because a row due exactly at its horizon is swept rather than collected.
        if next_look_at is None or next_look_at >= check.expires_at:
            return _CheckTransition(
                status=SignalReportCheck.Status.INCONCLUSIVE, next_run_at=None, runs_remaining=check.runs_remaining
            )
        return _CheckTransition(
            status=SignalReportCheck.Status.ACTIVE, next_run_at=next_look_at, runs_remaining=check.runs_remaining
        )

    runs_remaining = max(0, check.runs_remaining - 1)
    if runs_remaining == 0 or check.run_interval_minutes is None:
        return _CheckTransition(status=SignalReportCheck.Status.PASSED, next_run_at=None, runs_remaining=runs_remaining)
    next_run_at = now + timedelta(minutes=check.run_interval_minutes)
    if next_run_at > check.expires_at:
        return _CheckTransition(status=SignalReportCheck.Status.PASSED, next_run_at=None, runs_remaining=runs_remaining)
    return _CheckTransition(
        status=SignalReportCheck.Status.ACTIVE, next_run_at=next_run_at, runs_remaining=runs_remaining
    )


def record_check_verdict(
    check: SignalReportCheck,
    verdict: CheckVerdict,
    *,
    now: datetime | None = None,
    attribution: ArtefactAttribution | None = None,
    run_id: str | None = None,
    skill_name: str | None = None,
    refusal_reason: str | None = None,
    lane_can_emit_report: bool | None = None,
) -> None:
    """The single persistence funnel: append the result artefact and advance or retire the check.

    One transaction, and the row is re-read under a lock so a check cancelled while its query ran
    records nothing.

    `attribution` and `run_id` name the scout run that decided an `agent` check. A deterministic run
    has neither, so it keeps the `system()` attribution the executor writes under. `skill_name` and
    `refusal_reason` name the scout and the gate when the fleet refused to run an `agent` check.
    `lane_can_emit_report` says whether that run held `emit_report`, and None when nobody knows.
    """
    now = now or timezone.now()
    # The result's context is best-effort. A stored config can stop parsing part-way through a soak,
    # because a tightened query rule invalidates a class of stored queries at once. Such a run still
    # has to reach the errored path: raising here would record nothing, and the row would keep its
    # past `next_run_at` and head the due queue on every tick until its horizon.
    try:
        parsed = parse_check_config(check.kind, check.config)
    except CheckConfigValidationError:
        parsed = None
    config = parsed if isinstance(parsed, MetricThresholdConfig) else None

    with transaction.atomic():
        report = SignalReport.objects.select_for_update().filter(id=check.report_id, team_id=check.team_id).first()
        if report is None or report.effective_status != SignalReport.Status.RESOLVED:
            return
        current = (
            SignalReportCheck.objects.for_team(check.team_id)
            .select_for_update()
            .filter(id=check.id, status=SignalReportCheck.Status.ACTIVE)
            .first()
        )
        if (
            current is None
            or current.measurement_start_at != check.measurement_start_at
            or current.dispatched_at != check.dispatched_at
        ):
            return
        transition = _next_state(current, verdict, now)
        current.status = transition.status
        current.runs_remaining = transition.runs_remaining
        current.last_run_at = now
        current.last_outcome = verdict.outcome
        current.last_outcome_reason = verdict.reason
        if verdict.outcome == "errored":
            current.consecutive_errors += 1
        elif verdict.outcome != "inconclusive":
            current.consecutive_errors = 0
        current.consecutive_inconclusive = (
            current.consecutive_inconclusive + 1 if verdict.outcome == "inconclusive" else 0
        )
        if transition.next_run_at is not None:
            current.next_run_at = transition.next_run_at
        # Whatever the verdict, no run is waiting on this check any more. Clearing it here rather
        # than in the agent lane keeps the rule in one place: a row carrying `dispatched_at` is a
        # dispatch nobody has answered.
        current.dispatched_at = None
        current.save(
            update_fields=[
                "status",
                "runs_remaining",
                "last_run_at",
                "last_outcome",
                "last_outcome_reason",
                "consecutive_errors",
                "consecutive_inconclusive",
                "next_run_at",
                "dispatched_at",
                "updated_at",
            ]
        )
        SignalReportArtefact.add_log(
            team_id=current.team_id,
            report_id=str(current.report_id),
            content=CheckResult(
                check_id=str(current.id),
                kind=current.kind,
                title=current.title,
                outcome=verdict.outcome,
                explanation=verdict.explanation,
                reason=verdict.reason,
                observed_value=verdict.observed_value,
                baseline_value=config.baseline_value if config is not None else None,
                threshold=describe_comparison(config.comparison) if config is not None else None,
                run_id=run_id,
            ),
            attribution=attribution or ArtefactAttribution.system(),
        )
        if _should_resurface(current, verdict, lane_can_emit_report=lane_can_emit_report):
            baseline = config.baseline_value if config is not None else None
            threshold = describe_comparison(config.comparison) if config is not None else None
            transaction.on_commit(lambda: resurface_failed_check(current, verdict, baseline, threshold))
        # Post-commit, so a rolled-back verdict is never counted as one, and after the artefact so
        # the event describes a result a reader can already see on the report. The team comes off
        # the caller's row, where both call paths already select it with its organization; the
        # locked row selects neither, and widening the lock to reach them would take `FOR UPDATE`
        # on `Team`.
        transaction.on_commit(
            partial(
                capture_report_check_evaluated,
                check.team,
                current,
                run_id=run_id,
                skill_name=skill_name,
                reason=refusal_reason,
            )
        )


def _should_resurface(
    check: SignalReportCheck, verdict: CheckVerdict, *, lane_can_emit_report: bool | None = None
) -> bool:
    """Whether this verdict has to become a fresh report, because nothing else will carry it.

    A `metric_threshold` check has nobody in the loop, so a breach on a report the inbox no longer
    lists is an artefact on a closed item that no reader will open. An `agent` check has a scout in
    the loop, and the check brief tells a lane that holds `emit_report` to author the follow-up
    itself. A lane known to lack `emit_report` cannot, so its verdict takes the metric path. An
    unknown lane stays with the scout, because a second report for one relapse is a duplicate. Only
    a resolved report qualifies: a breach on a report still being worked lands where the person
    working it already looks.
    """
    if verdict.outcome != "failed" or check.report.effective_status != SignalReport.Status.RESOLVED:
        return False
    if check.kind == SignalReportCheck.Kind.METRIC_THRESHOLD:
        return True
    return check.kind == SignalReportCheck.Kind.AGENT and lane_can_emit_report is False


def resurface_failed_check(
    check: SignalReportCheck,
    verdict: CheckVerdict,
    baseline_value: float | None,
    threshold: str | None,
) -> None:
    """Emit the breach as a signal, so the pipeline authors a fresh report for the relapse.

    This is the same rule the grouping stage already applies to a resolved report: a signal that
    would have joined it starts a new report rather than reopening a terminal one. Grouping reads
    the `report_id` in `extra` and writes a typed `follow_up_of` link from the fresh report back to
    this one, carrying the verdict as the link's reason, so research starts from the fix the check
    was measuring. Best-effort, because the verdict is already on the report's log and losing the
    re-surface must not fail the tick that recorded it.
    """
    from asgiref.sync import async_to_sync  # noqa: PLC0415

    from products.signals.backend.facade.api import emit_signal  # noqa: PLC0415

    report = check.report
    description = "\n".join(
        [
            f"A follow-up check on a resolved report failed: {check.title}",
            "",
            f"Resolved report: {report.title or 'Untitled'} ({report.id})",
            f"What the check measured: {verdict.explanation}",
            *([f"Baseline when the check was written: {baseline_value}"] if baseline_value is not None else []),
            *([f"Expected: {threshold}"] if threshold else []),
        ]
    )
    try:
        async_to_sync(emit_signal)(
            team=report.team,
            source_product=SignalSourceProduct.SIGNALS_CHECK,
            source_type=SignalSourceType.CHECK_FAILED,
            source_id=f"check:{check.id}",
            description=description,
            weight=CHECK_FAILURE_SIGNAL_WEIGHT,
            extra={
                "check_id": str(check.id),
                "report_id": str(report.id),
                "check_title": check.title,
                "explanation": verdict.explanation,
                "observed_value": verdict.observed_value,
                "baseline_value": baseline_value,
                "threshold": threshold,
            },
            idempotency_key=str(check.id),
        )
    except Exception:
        logger.exception("signals.report_check.resurface_failed", check_id=str(check.id), team_id=check.team_id)


def _monitoring_metric_filter(disabled_organizations: frozenset[UUID], *, started_before: datetime | None = None) -> Q:
    reports = SignalReport.objects.filter(
        id=OuterRef("report_id"),
        team_id=OuterRef("team_id"),
        status=SignalReport.Status.MONITORING,
        monitoring_started_at__isnull=False,
    ).exclude(team__organization_id__in=disabled_organizations)
    if started_before is not None:
        reports = reports.filter(monitoring_started_at__lte=started_before)
    # Joined UPDATE filters become an ID subquery, so PostgreSQL cannot recheck stale check guards after a lock wait.
    return Q(Exists(reports), kind=SignalReportCheck.Kind.METRIC_THRESHOLD, config__monitoring__isnull=False) & ~Q(
        config__monitoring=None
    )


def _completed_check_runs(check: SignalReportCheck, start: datetime) -> int:
    completed = 0
    results = (
        SignalReportArtefact.objects.using("default")
        .filter(
            team_id=check.team_id,
            report_id=check.report_id,
            type=SignalReportArtefact.ArtefactType.CHECK_RESULT,
            created_at__gte=start,
        )
        .values_list("content", flat=True)
    )
    for content in results.iterator(chunk_size=100):
        try:
            result = CheckResult.model_validate_json(content)
        except ValueError:
            continue
        if result.check_id == str(check.id) and result.outcome == "passed":
            completed += 1
    return completed


def _resolved_monitoring_expiry(check: SignalReportCheck) -> datetime:
    start = check.report.monitoring_started_at
    if (
        check.kind != SignalReportCheck.Kind.METRIC_THRESHOLD
        or not check.config.get("monitoring")
        or start is None
        or check.measurement_start_at != start
        or check.expires_at != start + MAX_CHECK_HORIZON
    ):
        return check.expires_at
    if check.monitoring_fallback_expires_at is not None:
        return check.monitoring_fallback_expires_at
    ready_at = start + timedelta(minutes=check.soak_minutes or 0)
    try:
        config = cast(MetricThresholdConfig, parse_check_config(check.kind, check.config))
        query = resolve_check_query(config, check.report)
        ready_at = max(ready_at, metric_check_ready_at(query, check.report.team, start))
    except (CheckConfigValidationError, ValueError):
        pass
    runs = check.runs_remaining
    if check.run_interval_minutes and check.last_outcome is not None:
        runs += _completed_check_runs(check, start)
    return check_schedule_expires_at(
        next_run_at=ready_at,
        run_interval_minutes=check.run_interval_minutes,
        runs_remaining=runs,
        start_at=start,
    )


def _restore_resolved_monitoring_expiries(now: datetime, disabled_organizations: frozenset[UUID]) -> None:
    if not disabled_organizations:
        return
    candidates = (
        SignalReportCheck.all_teams.filter(
            _monitoring_metric_filter(frozenset()),
            report__team__organization_id__in=disabled_organizations,
            status=SignalReportCheck.Status.ACTIVE,
            measurement_start_at=F("report__monitoring_started_at"),
            expires_at=ExpressionWrapper(
                F("report__monitoring_started_at") + Value(MAX_CHECK_HORIZON), output_field=DateTimeField()
            ),
        )
        .filter(Q(monitoring_fallback_expires_at__isnull=True) | ~Q(monitoring_fallback_expires_at=F("expires_at")))
        .select_related("report__team")
        .order_by("expires_at", "id")[:MAX_CHECK_PARKS_PER_TICK]
    )
    for check in candidates:
        expires_at = _resolved_monitoring_expiry(check)
        period = SignalReport.objects.filter(
            id=OuterRef("report_id"),
            team_id=OuterRef("team_id"),
            status=SignalReport.Status.MONITORING,
            monitoring_started_at=check.report.monitoring_started_at,
        )
        SignalReportCheck.objects.for_team(check.team_id).filter(
            Exists(period),
            id=check.id,
            status=SignalReportCheck.Status.ACTIVE,
            updated_at=check.updated_at,
            expires_at=check.expires_at,
        ).update(expires_at=expires_at, monitoring_fallback_expires_at=expires_at, updated_at=now)


def expire_overdue_checks(now: datetime, *, disabled_monitoring_organization_ids: frozenset[UUID] | None = None) -> int:
    """Retire open checks whose horizon passed without a run. Returns how many were retired.

    Pending rows are swept too, so a check waiting on a report that never resolves retires at the
    horizon instead of waiting forever for a clock that will not start.
    """

    expiry_filter = Q(expires_at__lte=now)
    if disabled_monitoring_organization_ids is not None:
        monitoring = _monitoring_metric_filter(disabled_monitoring_organization_ids) & Q(
            status=SignalReportCheck.Status.ACTIVE
        )
        expiry_filter = (expiry_filter & ~monitoring) | (
            _monitoring_metric_filter(disabled_monitoring_organization_ids, started_before=now - MAX_CHECK_HORIZON)
            & Q(status=SignalReportCheck.Status.ACTIVE)
        )
    overdue = list(
        # Only the columns the log entry and the telemetry read. A `metric_threshold` config carries
        # a copied-in query, and a full tick hydrates five hundred rows.
        SignalReportCheck.all_teams.filter(expiry_filter, status__in=SignalReportCheck.OPEN_STATUSES).only(
            "id", "team_id", "report_id", "kind", "title", "last_run_at"
        )[:MAX_CHECK_EXPIRIES_PER_TICK]
    )
    if not overdue:
        return 0
    # The horizon is re-checked in the write. A report can resolve between the read and the write,
    # which arms its pending checks and moves `expires_at` forward, and an update filtered on id and
    # status alone would retire a check that has just been given a clock.
    expired = SignalReportCheck.all_teams.filter(
        expiry_filter,
        id__in=[check.id for check in overdue],
        status__in=SignalReportCheck.OPEN_STATUSES,
    ).update(status=SignalReportCheck.Status.EXPIRED, updated_at=now)
    if expired:
        _log_expired_checks(overdue, now, expired)
        _report_expired_checks(overdue)
    return expired


def _log_expired_checks(overdue: list[SignalReportCheck], now: datetime, expired: int) -> None:
    """Write one `check_expired` entry per row this sweep actually retired.

    Which rows those are is re-read when the write took fewer than the selection, because it skips
    a check whose report resolved in between. Telemetry can live with counting that row; the
    activity log cannot, because an entry saying a check retired is permanent and a reader acts on
    it. One transaction rather than one per row, so a full tick is a single commit ahead of the
    runs it delays.
    """
    retired = (
        {check.id for check in overdue}
        if expired == len(overdue)
        else set(
            SignalReportCheck.all_teams.filter(
                id__in=[check.id for check in overdue], status=SignalReportCheck.Status.EXPIRED, updated_at=now
            ).values_list("id", flat=True)
        )
    )
    with transaction.atomic():
        for check in overdue:
            if check.id in retired:
                write_check_expired(check, now)


def _report_expired_checks(overdue: list[SignalReportCheck]) -> None:
    """Emit one expiry event per project for the rows a sweep selected.

    Counted from the selection rather than the write, so a row armed in between is over-counted by
    one. That is acceptable for telemetry and saves a second read of every retired row.
    """
    per_team: dict[int, list[datetime | None]] = {}
    for check in overdue:
        per_team.setdefault(check.team_id, []).append(check.last_run_at)
    try:
        teams = Team.objects.filter(id__in=per_team.keys()).select_related("organization")
        for team in teams:
            last_runs = per_team[team.id]
            capture_report_checks_expired(
                team,
                expired_count=len(last_runs),
                never_ran_count=sum(1 for last_run_at in last_runs if last_run_at is None),
            )
    except Exception:
        logger.exception("signals.report_check.expired_report_failed")


def _park_checks(active: Iterable[SignalReportCheck], now: datetime, *, resolved_status_filter: Q | None = None) -> int:
    parked = 0
    team_filters: dict[int, Q] = {}
    monitoring_enabled: dict[int, bool] = {}
    for check in active:
        status_filter = resolved_status_filter
        if status_filter is None:
            if check.team_id not in team_filters:
                team_filters[check.team_id] = report_status_filter(
                    [SignalReport.Status.RESOLVED, SignalReport.Status.MONITORING],
                    team_id=check.team_id,
                    field="report__status",
                )
            status_filter = team_filters[check.team_id]
        soak_minutes = check.soak_minutes
        if soak_minutes is None:
            # A legacy row's retry or recurring date no longer identifies its initial soak.
            soak_minutes = (
                DEFAULT_CHECK_SOAK_HOURS * 60
                if check.last_run_at is not None or check.dispatched_at is not None
                else soak_minutes_from_gap(check.next_run_at, check.created_at)
            )
        preserve_monitoring_errors = False
        if (
            check.kind == SignalReportCheck.Kind.METRIC_THRESHOLD
            and check.config.get("monitoring")
            and check.measurement_start_at is not None
            and check.measurement_start_at == check.report.monitoring_started_at
        ):
            if check.team_id not in monitoring_enabled:
                monitoring_enabled[check.team_id] = team_report_monitoring_enabled(check.team_id)
            preserve_monitoring_errors = monitoring_enabled[check.team_id]
        parked += (
            SignalReportCheck.objects.for_team(check.team_id)
            .filter(id=check.id, status=SignalReportCheck.Status.ACTIVE)
            .exclude(status_filter)
            .update(
                status=SignalReportCheck.Status.PENDING,
                soak_minutes=soak_minutes,
                measurement_start_at=None,
                next_run_at=now + timedelta(minutes=soak_minutes),
                expires_at=now + MAX_CHECK_HORIZON,
                monitoring_fallback_expires_at=F("monitoring_fallback_expires_at")
                if check.report.monitoring_started_at is not None
                else None,
                consecutive_errors=F("consecutive_errors") if preserve_monitoring_errors else 0,
                consecutive_inconclusive=0,
                dispatched_at=None,
                updated_at=now,
            )
        )
    return parked


def park_report_checks_on_reopen(*, team_id: int, report_id: str, now: datetime) -> int:
    new_period = SignalReport.objects.filter(id=report_id, team_id=team_id, monitoring_started_at__isnull=True)
    SignalReportCheck.objects.for_team(team_id).filter(
        Exists(new_period),
        report_id=report_id,
        status=SignalReportCheck.Status.PENDING,
        monitoring_fallback_expires_at__isnull=False,
    ).update(monitoring_fallback_expires_at=None, updated_at=now)
    return _park_checks(
        SignalReportCheck.objects.for_team(team_id)
        .filter(report_id=report_id, status=SignalReportCheck.Status.ACTIVE)
        .select_related("report"),
        now,
    )


def park_checks_on_unresolved_reports(
    now: datetime, *, disabled_monitoring_organization_ids: frozenset[UUID] | None = None
) -> int:
    """Park active checks whose report no longer has an implemented fix. Returns how many moved.

    A check can be active on an unresolved report in three ways: a report that left `resolved`
    (reopened, archived, or restored somewhere else), a row written active before the create path
    made the report decide, and any write path that skips `create_check`. Such a check must not run
    or spend its error budget before a fix is live. As a pending row, the next resolve arms it
    through `arm_pending_checks` with a fresh soak, and the expiry sweep retires it if the report
    never resolves.

    A dated row keeps the gap its author left as its soak. An interrupted Monitoring period keeps
    its error streak so restoring it cannot postpone a retry or reset the error budget.
    """
    candidates = SignalReportCheck.all_teams.filter(status=SignalReportCheck.Status.ACTIVE)
    if disabled_monitoring_organization_ids is None:
        disabled_monitoring_organization_ids = check_monitoring_disabled_organizations(candidates)
    status_filter = report_status_filter(
        [SignalReport.Status.RESOLVED, SignalReport.Status.MONITORING],
        field="report__status",
        disabled_monitoring_organization_ids=disabled_monitoring_organization_ids,
    )
    active = list(
        candidates.exclude(status_filter)
        .select_related("report")
        .only(
            "id",
            "team_id",
            "created_at",
            "next_run_at",
            "soak_minutes",
            "last_run_at",
            "dispatched_at",
            "kind",
            "config",
            "measurement_start_at",
            "report__monitoring_started_at",
        )[:MAX_CHECK_PARKS_PER_TICK]
    )
    parked = _park_checks(active, now, resolved_status_filter=status_filter)
    if parked:
        logger.info("signals.report_check.parked_on_unresolved_report", parked=parked)
    return parked


def _monitoring_window_end_expression() -> ExpressionWrapper:
    return ExpressionWrapper(
        F("report__monitoring_started_at") + Coalesce("soak_minutes", Value(0)) * Value(timedelta(minutes=1)),
        output_field=DateTimeField(),
    )


def _prepare_monitoring_metrics(now: datetime, disabled_organizations: frozenset[UUID]) -> None:
    cadence = ExpressionWrapper(
        Greatest(
            Coalesce("run_interval_minutes", Value(DEFAULT_MONITORING_INTERVAL_MINUTES)),
            Value(MIN_CHECK_INTERVAL_MINUTES),
        )
        * Value(timedelta(minutes=1)),
        output_field=DurationField(),
    )
    candidates = (
        SignalReportCheck.all_teams.filter(
            _monitoring_metric_filter(disabled_organizations),
            status=SignalReportCheck.Status.ACTIVE,
        )
        .annotate(_monitoring_ends_at=_monitoring_window_end_expression())
        .annotate(
            _monitoring_next_run_at=Least(
                F("_monitoring_ends_at"),
                ExpressionWrapper(
                    Greatest(
                        Coalesce("last_run_at", F("report__monitoring_started_at")), F("report__monitoring_started_at")
                    )
                    + Case(
                        When(
                            last_run_at__gte=F("report__monitoring_started_at"),
                            consecutive_errors__gt=0,
                            then=Value(CHECK_ERROR_RETRY_AFTER),
                        ),
                        default=cadence,
                        output_field=DurationField(),
                    ),
                    output_field=DateTimeField(),
                ),
            ),
            _monitoring_expires_at=ExpressionWrapper(
                F("report__monitoring_started_at") + Value(MAX_CHECK_HORIZON), output_field=DateTimeField()
            ),
        )
        .exclude(
            measurement_start_at=F("report__monitoring_started_at"),
            next_run_at=F("_monitoring_next_run_at"),
            expires_at=F("_monitoring_expires_at"),
        )
        .select_related("report")
        .order_by("report__monitoring_started_at", "id")[:MAX_CHECK_PARKS_PER_TICK]
    )
    for check in candidates:
        start = check.report.monitoring_started_at
        assert start is not None
        period = SignalReport.objects.filter(
            id=OuterRef("report_id"),
            team_id=OuterRef("team_id"),
            status=SignalReport.Status.MONITORING,
            monitoring_started_at=start,
        )
        SignalReportCheck.objects.for_team(check.team_id).filter(
            Exists(period),
            id=check.id,
            status=SignalReportCheck.Status.ACTIVE,
            updated_at=check.updated_at,
        ).update(
            next_run_at=check._monitoring_next_run_at,
            measurement_start_at=start,
            expires_at=check._monitoring_expires_at,
            monitoring_fallback_expires_at=check.expires_at
            if (
                check.monitoring_fallback_expires_at is None
                and check.measurement_start_at == start
                and check.expires_at < start + MAX_CHECK_HORIZON
            )
            else check.monitoring_fallback_expires_at,
            updated_at=now,
        )


def collect_due_checks(
    now: datetime,
    *,
    limit: int = MAX_CHECK_RUNS_PER_TICK,
    disabled_monitoring_organization_ids: frozenset[UUID] | None = None,
) -> list[SignalReportCheck]:
    """The checks to run this tick, most overdue first and capped per team.

    The horizon is read here rather than trusted to the expiry sweep. That sweep is bounded per
    tick, and a check sitting at its horizon is always due as well, so a backlog larger than the
    sweep would otherwise let a row measure after the horizon it was supposed to retire at.
    """

    eligible_checks = SignalReportCheck.all_teams.filter(
        status=SignalReportCheck.Status.ACTIVE, next_run_at__lte=now, expires_at__gt=now
    )
    if disabled_monitoring_organization_ids is None:
        disabled_monitoring_organization_ids = check_monitoring_disabled_organizations(eligible_checks)
    candidates = (
        eligible_checks.annotate(_monitoring_ends_at=_monitoring_window_end_expression())
        .filter(
            _monitoring_metric_filter(disabled_monitoring_organization_ids),
            report__monitoring_started_at__gt=now - MAX_CHECK_HORIZON,
            _monitoring_ends_at__gt=now,
        )
        .select_related("report", "report__team", "team__organization")
        # Rank each team's rows against its own, then read those ranks in order, so every team's
        # oldest check sorts ahead of any team's second. Ordering by `next_run_at` alone would let
        # one team's backlog fill the whole prefix and starve every other team behind it.
        .annotate(
            _team_rank=Window(
                expression=RowNumber(),
                partition_by=[F("team_id")],
                order_by=[F("next_run_at").asc(), F("id").asc()],
            )
        )
        .order_by("_team_rank", "next_run_at", "id")[: limit * MAX_CHECK_RUNS_PER_TEAM_PER_TICK]
    )
    per_team: dict[int, int] = {}
    due: list[SignalReportCheck] = []
    for check in candidates:
        taken = per_team.get(check.team_id, 0)
        if taken >= MAX_CHECK_RUNS_PER_TEAM_PER_TICK:
            continue
        per_team[check.team_id] = taken + 1
        due.append(check)
        if len(due) >= limit:
            break
    return due


def _arm_monitoring_checks(now: datetime, *, disabled_monitoring_organization_ids: frozenset[UUID]) -> None:
    from products.signals.backend.report_check_authoring import arm_pending_checks

    pending_checks = SignalReportCheck.all_teams.filter(
        team_id=OuterRef("team_id"),
        report_id=OuterRef("id"),
        status=SignalReportCheck.Status.PENDING,
        expires_at__gt=now,
    )
    reports = (
        SignalReport.objects.filter(
            Exists(pending_checks),
            status=SignalReport.Status.MONITORING,
            monitoring_started_at__isnull=False,
        )
        .exclude(team__organization_id__in=disabled_monitoring_organization_ids)
        .select_related("team")
        .only("id", "status", "team_id", "monitoring_started_at", "team__organization_id")
        .order_by("id")[:MAX_CHECK_PARKS_PER_TICK]
    )
    for report in reports:
        arm_pending_checks(
            team_id=report.team_id,
            report_id=report.id,
            resolved_at=now,
            expected_monitoring_started_at=report.monitoring_started_at,
        )


def run_due_report_checks(*, now: datetime | None = None, limit: int = MAX_CHECK_RUNS_PER_TICK) -> CheckRunSummary:
    """Expire stale checks and record due interim measurements during enabled Monitoring."""

    now = now or timezone.now()
    candidate_checks = SignalReportCheck.all_teams.filter(
        Q(status=SignalReportCheck.Status.ACTIVE) | Q(status=SignalReportCheck.Status.PENDING, expires_at__gt=now)
    )
    disabled_organizations = check_monitoring_disabled_organizations(candidate_checks)
    _prepare_monitoring_metrics(now, disabled_organizations)
    expired = expire_overdue_checks(now, disabled_monitoring_organization_ids=disabled_organizations)
    _arm_monitoring_checks(now, disabled_monitoring_organization_ids=disabled_organizations)
    park_checks_on_unresolved_reports(now, disabled_monitoring_organization_ids=disabled_organizations)
    deadline = time.monotonic() + CHECK_RUN_TIME_BUDGET_SECONDS
    counts: dict[str, int] = {
        "observed": 0,
        "passed": 0,
        "failed": 0,
        "errored": 0,
        "inconclusive": 0,
        "dispatched": 0,
        "deferred": 0,
        "cancelled": 0,
    }
    for check in collect_due_checks(now, limit=limit, disabled_monitoring_organization_ids=disabled_organizations):
        if time.monotonic() >= deadline:
            break
        try:
            observation = measure_monitoring_check(check, now=now, deadline=deadline)
            counts["observed"] += int(record_monitoring_observation(check, observation))
        except (MetricQueryBudgetExhausted, MonitoringWindowClosed):
            counts["deferred"] += 1
        except Exception:
            logger.exception(
                "signals.report_check.monitoring_step_failed", check_id=str(check.id), team_id=check.team_id
            )
    return CheckRunSummary(expired=expired, **counts)
