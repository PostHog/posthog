"""Execution of the checks attached to signal reports.

The coordinator calls ``run_due_report_checks`` on its tick, and each due check advances by one
step. A ``metric_threshold`` check is answered here and then: one bounded Trends query, one
comparison, one artefact, with no sandbox, no scout enrolment, and no LLM. An ``agent`` check needs
a run to decide it, so it is handed to ``report_check_agent`` and closed later by the tool that run
calls.

Both lanes end in ``record_check_verdict``, which is the only writer of a check's outcome: one
artefact appended and one row advanced or retired, whatever decided the verdict.

The comparison is the alerts product's, not a second one written here, so a check and an alert word
a breach the same way and there is one place where "is this value out of bounds?" is decided.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from functools import partial

from django.db import transaction
from django.db.models import F, Window
from django.db.models.functions import RowNumber
from django.utils import timezone

import structlog

from posthog.schema import (
    AlertCondition,
    AlertConditionType,
    InsightsThresholdBounds,
    InsightThreshold,
    InsightThresholdType,
)

from posthog.clickhouse.query_tagging import tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team

from products.alerts.backend.facade.evaluation import (
    ComparableSeries,
    ExtractionResult,
    SeriesPoint,
    evaluate_threshold,
)
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import CheckResult
from products.signals.backend.enums import SignalSourceProduct, SignalSourceType
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportCheck
from products.signals.backend.report_check_artefacts import write_check_expired
from products.signals.backend.report_check_telemetry import (
    capture_report_check_evaluated,
    capture_report_checks_expired,
)
from products.signals.backend.report_checks import (
    MAX_CONSECUTIVE_CHECK_ERRORS,
    CheckComparison,
    CheckConfigValidationError,
    CheckOutcome,
    MetricThresholdConfig,
    parse_check_config,
)
from products.signals.backend.report_metric_refresh import measure_metric
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
# Same bound the scout runner puts on a stored failure reason.
MAX_CHECK_ERROR_REASON_LENGTH = 300
# Weight of the signal a failed check on a resolved report emits. High enough to promote on its own:
# a fix that stopped holding is a finding somebody already decided was worth fixing once.
CHECK_FAILURE_SIGNAL_WEIGHT = 1.0

# A check stops running while its report is soft-deleted or suppressed, and runs again when the report
# comes back. Its horizon keeps advancing meanwhile: a check that outlives `expires_at` while paused
# expires like any other, because the soak window is the author's deadline, not the report's.
CHECKABLE_REPORT_STATUSES = tuple(
    status
    for status in SignalReport.Status.values
    if status not in {SignalReport.Status.DELETED, SignalReport.Status.SUPPRESSED}
)


@frozen
class CheckRunSummary:
    expired: int
    passed: int
    failed: int
    errored: int
    # An `agent` check the tick started a scout run for, and one the fleet could not take yet.
    # Neither is an outcome: both rows are still active and still owe a verdict.
    dispatched: int = 0
    deferred: int = 0


@frozen
class CheckVerdict:
    outcome: CheckOutcome
    explanation: str
    observed_value: float | None = None


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


def _threshold_for(comparison: CheckComparison) -> InsightThreshold:
    """The alerts threshold whose breach is exactly this comparison's failure.

    The alerts comparator breaches on `value < lower` or `value > upper`, so `gte` is a lower bound,
    `lte` an upper one, and `between` both.
    """
    if comparison.operator == "between":
        assert comparison.bounds is not None
        bounds = InsightsThresholdBounds(lower=comparison.bounds.lower, upper=comparison.bounds.upper)
    elif comparison.operator == "gte":
        bounds = InsightsThresholdBounds(lower=comparison.value)
    else:
        bounds = InsightsThresholdBounds(upper=comparison.value)
    return InsightThreshold(type=InsightThresholdType.ABSOLUTE, bounds=bounds)


def _describe_comparison(comparison: CheckComparison) -> str:
    if comparison.operator == "between":
        assert comparison.bounds is not None
        return f"between {comparison.bounds.lower} and {comparison.bounds.upper}"
    return f"at most {comparison.value}" if comparison.operator == "lte" else f"at least {comparison.value}"


def evaluate_check_value(*, comparison: CheckComparison, observed_value: float, subject: str) -> CheckVerdict:
    """Compare one measured value against the check's expectation."""

    result = ExtractionResult(
        series=[
            ComparableSeries(label=subject, points=[SeriesPoint(date=None, value=observed_value)], current_index=0)
        ],
        subject=subject,
        framed=False,
    )
    evaluation = evaluate_threshold(
        result,
        AlertCondition(type=AlertConditionType.ABSOLUTE_VALUE),
        _threshold_for(comparison),
    )
    if evaluation.breaches:
        return CheckVerdict(outcome="failed", explanation=evaluation.breaches[0], observed_value=observed_value)
    return CheckVerdict(
        outcome="passed",
        explanation=f"{subject} ({observed_value}) is {_describe_comparison(comparison)}, as expected",
        observed_value=observed_value,
    )


def _errored_explanation(error: Exception, *, subject: str) -> str:
    """The line a report reader sees when a run could not be measured.

    It opens with the check's title, as the passed and failed lines do, so a report carrying several
    checks does not log entries a reader cannot tell apart.

    Our own validation and resolution failures name something the reader can act on, so they are
    kept. Anything else is reduced to the fixed line: a query error can carry generated SQL and a
    server stack trace, which `ExposedCHQueryError` exists to keep out of user-facing text, and the
    artefact log is permanent and rendered as written. `logger.exception` above holds the whole
    error either way.
    """
    reason = str(error).strip() if isinstance(error, ValueError | TimeoutError) else ""
    if not reason:
        return f"{subject} could not be measured."
    return f"{subject} could not be measured: {reason[:MAX_CHECK_ERROR_REASON_LENGTH]}"


def measure_check(check: SignalReportCheck, *, deadline: float) -> CheckVerdict:
    """Run one check and return its verdict. Never raises: a failure to measure is an `errored` verdict."""

    try:
        config = parse_check_config(check.kind, check.config)
        assert isinstance(config, MetricThresholdConfig)
        query = resolve_check_query(config, check.report)
        tag_queries(trigger="signals_report_check")
        measurement = measure_metric(query, check.report.team, deadline=deadline, include_series=False)
    except Exception as error:
        logger.exception("signals.report_check.measurement_failed", check_id=str(check.id), team_id=check.team_id)
        return CheckVerdict(outcome="errored", explanation=_errored_explanation(error, subject=check.title))
    return evaluate_check_value(comparison=config.comparison, observed_value=measurement.value, subject=check.title)


def _next_state(check: SignalReportCheck, verdict: CheckVerdict, now: datetime) -> _CheckTransition:
    """The check's status after this verdict, its next run time, and its remaining runs.

    Re-arming anchors on `now` rather than the missed slot, so a coordinator outage cannot leave a
    recurring check owing a burst of catch-up runs.
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
) -> None:
    """The single persistence funnel: append the result artefact and advance or retire the check.

    One transaction, and the row is re-read under a lock so a check cancelled while its query ran
    records nothing.

    `attribution` and `run_id` name the scout run that decided an `agent` check. A deterministic run
    has neither, so it keeps the `system()` attribution the executor writes under.
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
        current = (
            SignalReportCheck.objects.for_team(check.team_id)
            .select_for_update()
            .filter(id=check.id, status=SignalReportCheck.Status.ACTIVE)
            .first()
        )
        if current is None:
            return
        transition = _next_state(current, verdict, now)
        current.status = transition.status
        current.runs_remaining = transition.runs_remaining
        current.last_run_at = now
        current.last_outcome = verdict.outcome
        current.consecutive_errors = current.consecutive_errors + 1 if verdict.outcome == "errored" else 0
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
                "consecutive_errors",
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
                observed_value=verdict.observed_value,
                baseline_value=config.baseline_value if config is not None else None,
                threshold=_describe_comparison(config.comparison) if config is not None else None,
                run_id=run_id,
            ),
            attribution=attribution or ArtefactAttribution.system(),
        )
        if _should_resurface(current, verdict):
            baseline = config.baseline_value if config is not None else None
            threshold = _describe_comparison(config.comparison) if config is not None else None
            transaction.on_commit(lambda: resurface_failed_check(current, verdict, baseline, threshold))
        # Post-commit, so a rolled-back verdict is never counted as one, and after the artefact so
        # the event describes a result a reader can already see on the report. The team comes off
        # the caller's row, where both call paths already select it with its organization; the
        # locked row selects neither, and widening the lock to reach them would take `FOR UPDATE`
        # on `Team`.
        transaction.on_commit(partial(capture_report_check_evaluated, check.team, current, run_id=run_id))


def _should_resurface(check: SignalReportCheck, verdict: CheckVerdict) -> bool:
    """Whether this verdict has to become a fresh report, because nothing else will carry it.

    An `agent` check has a scout in the loop that can author one. A `metric_threshold` check has
    nobody, so a breach on a report the inbox no longer lists is an artefact on a closed item that
    no reader will open. Only a resolved report qualifies: a breach on a report still being worked
    lands where the person working it already looks.
    """
    return (
        verdict.outcome == "failed"
        and check.kind == SignalReportCheck.Kind.METRIC_THRESHOLD
        and check.report.status == SignalReport.Status.RESOLVED
    )


def resurface_failed_check(
    check: SignalReportCheck,
    verdict: CheckVerdict,
    baseline_value: float | None,
    threshold: str | None,
) -> None:
    """Emit the breach as a signal, so the pipeline authors a fresh report for the relapse.

    This is the same rule the grouping stage already applies to a resolved report: a signal that
    would have joined it starts a new report linked by `related_to` rather than reopening a
    terminal one. Best-effort — the verdict is already on the report's log, and losing the
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


def expire_overdue_checks(now: datetime) -> int:
    """Retire open checks whose horizon passed without a run. Returns how many were retired.

    Pending rows are swept too, so a check waiting on a report that never resolves retires at the
    horizon instead of waiting forever for a clock that will not start.
    """

    overdue = list(
        # Only the columns the log entry and the telemetry read. A `metric_threshold` config carries
        # a copied-in query, and a full tick hydrates five hundred rows.
        SignalReportCheck.all_teams.filter(status__in=SignalReportCheck.OPEN_STATUSES, expires_at__lte=now).only(
            "id", "team_id", "report_id", "kind", "title", "last_run_at"
        )[:MAX_CHECK_EXPIRIES_PER_TICK]
    )
    if not overdue:
        return 0
    # The horizon is re-checked in the write. A report can resolve between the read and the write,
    # which arms its pending checks and moves `expires_at` forward, and an update filtered on id and
    # status alone would retire a check that has just been given a clock.
    expired = SignalReportCheck.all_teams.filter(
        id__in=[check.id for check in overdue],
        status__in=SignalReportCheck.OPEN_STATUSES,
        expires_at__lte=now,
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


def collect_due_checks(now: datetime, *, limit: int = MAX_CHECK_RUNS_PER_TICK) -> list[SignalReportCheck]:
    """The checks to run this tick, most overdue first and capped per team.

    The horizon is read here rather than trusted to the expiry sweep. That sweep is bounded per
    tick, and a check sitting at its horizon is always due as well, so a backlog larger than the
    sweep would otherwise let a row measure after the horizon it was supposed to retire at.
    """

    candidates = (
        SignalReportCheck.all_teams.filter(
            status=SignalReportCheck.Status.ACTIVE,
            next_run_at__lte=now,
            expires_at__gt=now,
            report__status__in=CHECKABLE_REPORT_STATUSES,
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


def run_due_report_checks(*, now: datetime | None = None, limit: int = MAX_CHECK_RUNS_PER_TICK) -> CheckRunSummary:
    """Expire what timed out, then advance every check due this tick by one step.

    A `metric_threshold` check is measured and recorded here. An `agent` check is dispatched (or
    its overdue dispatch is written off), and the run it started records the verdict later, so the
    tick's time budget bounds the dispatch and not the investigation.
    """

    now = now or timezone.now()
    expired = expire_overdue_checks(now)
    deadline = time.monotonic() + CHECK_RUN_TIME_BUDGET_SECONDS
    counts: dict[str, int] = {"passed": 0, "failed": 0, "errored": 0, "dispatched": 0, "deferred": 0}
    for check in collect_due_checks(now, limit=limit):
        if time.monotonic() >= deadline:
            break
        if check.kind == SignalReportCheck.Kind.AGENT:
            # Deferred: the agent lane reaches the scout harness and the Temporal client, and this
            # module is imported by the REST route load, which never dispatches anything.
            from products.signals.backend.report_check_agent import run_agent_check  # noqa: PLC0415

            try:
                counts[run_agent_check(check, now=now)] += 1
            except Exception:
                logger.exception(
                    "signals.report_check.agent_step_failed", check_id=str(check.id), team_id=check.team_id
                )
            continue
        verdict = measure_check(check, deadline=deadline)
        try:
            record_check_verdict(check, verdict)
        except Exception:
            logger.exception("signals.report_check.persist_failed", check_id=str(check.id), team_id=check.team_id)
            continue
        counts[verdict.outcome] += 1
    return CheckRunSummary(expired=expired, **counts)
