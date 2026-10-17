"""Evaluation of due metrics alerts on the shared alerts platform.

Reads a batch of checks from the shared platform and reports what it decided. It writes
nothing: the platform records the batch in its own activity after Temporal holds the deliveries
this returned, so an attempt that dies mid-flight costs its queries and nothing else.

The shape copies the logs source (`products/logs/backend/alert_source_cycle.py`) so the two
adapters hook into the same lifecycle the same way. What differs is below the query: a metrics
alert runs one query per configuration through the product's own query facade, anchors its
window on the due slot with an explicit interval, and clamps the window end to the ingestion
checkpoint. Each clause is its own ClickHouse query, so there is no logs-style single-scan cohort
and this module does not pretend to batch.
"""

import math
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.errors import ExposedHogQLError

from posthog.dataclasses import frozen
from posthog.errors import ExposedCHQueryError, QueryErrorCategory, classify_query_error
from posthog.models import Team

from products.alerts_platform.backend.facade.api import due_checks, slot_of
from products.alerts_platform.backend.facade.contracts import (
    SOURCE_CONDITION_KEY,
    AlertEventKind,
    MuteReason,
    PlatformAlertCheckInput,
    PlatformAlertOutcome,
    SkipReason,
    SourceBatchEvaluation,
    SourceKind,
)
from products.alerts_platform.backend.facade.lifecycle import (
    NOTIFICATION_EVENT_KINDS,
    PLATFORM_LOGS_ALERT_POLICY,
    AlertCheckOutcome,
    AlertSnapshot,
    AlertState,
    CheckInput,
    ControlPlaneOutcome,
    NotificationAction,
    Outcome,
    apply_broken_config,
    decide_firing_episode,
    evaluate_alert_check,
)
from products.alerts_platform.backend.facade.platform_metrics import (
    increment_checks,
    increment_checks_skipped,
    increment_notifications_muted,
    increment_state_transition,
    record_batch_duration,
    record_scheduler_lag,
    safe_record,
)
from products.alerts_platform.backend.facade.scheduling import is_utc_datetime_blocked, parse_blocked_windows_tuples
from products.metrics.backend.alert_checkpoint import fetch_live_metrics_checkpoint, resolve_alert_date_to
from products.metrics.backend.facade.api import run_metric_query
from products.metrics.backend.facade.contracts import (
    MAX_CLAUSES_PER_QUERY,
    MetricFilter,
    MetricGroupBy,
    MetricQueryClause,
    MetricQueryRequest,
    MetricSeries,
)
from products.metrics.backend.facade.enums import AttributeScope, FilterOp, MetricAggregation, MetricType

# Private to the product's query runner. The alert must end its window on the same bucket boundary the
# runner starts its buckets on, or the current window is a partial bucket.
from products.metrics.backend.metric_query_runner import _align_to_interval

logger = structlog.get_logger(__name__)

# The same bounds the logs source runs under, so both sources fit the same activity timeouts.
# ClickHouse time for the batch. `EVALUATE_START_TO_CLOSE` in the workflow sits above it, so an
# overrunning query is ended by ClickHouse rather than by the activity.
BATCH_QUERY_BUDGET_SECONDS = 25
# No single alert's query may spend the whole batch budget.
MAX_QUERY_SECONDS = 20
# Below this there is no point starting another query; the alert keeps its due time instead.
MIN_QUERY_SECONDS = 2

# One evaluation window is one bucket of the metrics runner, so the window must be one of the
# runner's intervals. An explicit interval keeps `evaluation_key` stable across retries; an
# auto-picked one changes with the span.
WINDOW_TO_INTERVAL: dict[int, str] = {
    1: "minute",
    5: "minute_5",
    15: "minute_15",
    60: "hour",
    360: "hour_6",
    1440: "day",
}

_POLICY = PLATFORM_LOGS_ALERT_POLICY


class MetricsAlertFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    op: FilterOp = FilterOp.EQ
    value: str
    scope: AttributeScope = AttributeScope.AUTO


class MetricsAlertGroupBy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    scope: AttributeScope = AttributeScope.AUTO


class MetricsAlertClause(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    metric_name: str = Field(min_length=1)
    aggregation: MetricAggregation
    filters: list[MetricsAlertFilter] = []
    group_by: list[MetricsAlertGroupBy] = []
    quantile: float | None = None
    metric_type: MetricType | None = None


class MetricsAlertCondition(BaseModel):
    """The metrics bound, which the platform keeps under `source_config["condition"]`.

    The keys match the logs source's condition. The threshold is any finite number, because a
    metric value is a float that can be negative, where a log count is a whole number.
    """

    model_config = ConfigDict(extra="forbid")
    threshold_count: float
    threshold_operator: Literal["above", "below"]
    window_minutes: int

    @field_validator("threshold_count")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("threshold must be a finite number")
        return value


class MetricsAlertSource(BaseModel):
    """The `source_config` of a `source_kind="metrics"` configuration."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    type: Literal["MetricsAlertSource"] = "MetricsAlertSource"
    clauses: list[MetricsAlertClause] = Field(min_length=1, max_length=MAX_CLAUSES_PER_QUERY)
    formula: str | None = None
    value_clause: str | None = None
    condition: MetricsAlertCondition = Field(alias=SOURCE_CONDITION_KEY)

    def evaluated_clause(self) -> str:
        return "formula" if self.formula is not None else (self.value_clause or self.clauses[0].name)


def parse_source(source_config: dict[str, Any]) -> MetricsAlertSource:
    return MetricsAlertSource.model_validate(source_config)


def _broken_reason(check: PlatformAlertCheckInput) -> str | None:
    """Why a configuration can never be evaluated, or None when a query can answer it."""
    try:
        source = parse_source(check.source_config)
    except ValidationError as error:
        return f"invalid source config: {error.errors()[0].get('msg', 'invalid')}"
    if source.condition.window_minutes not in WINDOW_TO_INTERVAL:
        return f"unsupported window of {source.condition.window_minutes} minutes"
    for clause in source.clauses:
        # An unaggregated clause returns one series per physical series and looks up each one's
        # labels in a query of its own, which the check's query budget does not cover.
        if clause.aggregation.is_raw:
            return f"clause {clause.name!r} needs an aggregation"
    if source.formula is None and source.value_clause is not None:
        if source.value_clause not in {clause.name for clause in source.clauses}:
            return f"value clause {source.value_clause!r} is not one of the clauses"
    return None


def _request(source: MetricsAlertSource, check: PlatformAlertCheckInput, date_to: datetime) -> MetricQueryRequest:
    # Contiguous windows: N-of-M reads the newest `evaluation_periods` buckets of one query, so no
    # history table is needed and a retry reads the same buckets.
    window_minutes = source.condition.window_minutes
    lookback = timedelta(minutes=window_minutes * check.evaluation_periods)
    clauses = tuple(
        MetricQueryClause(
            name=clause.name,
            metric_name=clause.metric_name,
            aggregation=clause.aggregation,
            filters=tuple(MetricFilter(key=f.key, op=f.op, value=f.value, scope=f.scope) for f in clause.filters),
            group_by=tuple(MetricGroupBy(key=g.key, scope=g.scope) for g in clause.group_by),
            quantile=clause.quantile,
            metric_type=clause.metric_type,
        )
        for clause in source.clauses
    )
    return MetricQueryRequest(
        clauses=clauses,
        date_from=date_to - lookback,
        date_to=date_to,
        interval=WINDOW_TO_INTERVAL[window_minutes],
        formula=source.formula,
    )


def _bucket_instant(time: str) -> float:
    parsed = datetime.fromisoformat(time)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _values_newest_first(
    series: MetricSeries, evaluation_periods: int, *, window_end: datetime, window: timedelta
) -> tuple[float | None, ...]:
    """The value of each expected window, newest first, read by bucket time rather than by list
    position: a bucket the query did not return is unknown, not the next older bucket and not zero."""
    by_instant = {_bucket_instant(point.time): point.value for point in series.points}
    return tuple(by_instant.get((window_end - window * (index + 1)).timestamp()) for index in range(evaluation_periods))


def _breached(value: float | None, threshold_count: float, threshold_operator: str) -> bool | None:
    if value is None:
        return None
    if threshold_operator == "above":
        return value > threshold_count
    return value < threshold_count


def _is_in_quiet_hours(check: PlatformAlertCheckInput, now: datetime, tz_name: str) -> bool:
    if not check.schedule_restriction:
        return False
    try:
        return is_utc_datetime_blocked(now, tz_name, parse_blocked_windows_tuples(check.schedule_restriction))
    except Exception as error:
        # A restriction we cannot parse must not decide the alert either way.
        logger.exception(
            "Unparseable schedule restriction; evaluating anyway", check_id=str(check.id), error=str(error)
        )
        return False


def _snapshot(check: PlatformAlertCheckInput, prior_breached: tuple[bool, ...]) -> AlertSnapshot:
    return AlertSnapshot(
        state=AlertState(check.state),
        cooldown=timedelta(minutes=check.cooldown_minutes),
        last_notified_at=check.last_notified_at,
        snooze_until=check.snooze_until,
        consecutive_failures=check.consecutive_failures,
        evaluation_periods=check.evaluation_periods,
        datapoints_to_alarm=check.datapoints_to_alarm,
        recent_events_breached=prior_breached,
        firing_started_at=check.firing_started_at,
    )


# What one check decided. A metrics configuration owns no destinations yet, so a check records an
# outcome and requests no delivery: `SourceBatchEvaluation.deliveries` stays empty.
Decision = PlatformAlertOutcome


@frozen
class _Triage:
    decided: list[Decision]
    evaluable: list[PlatformAlertCheckInput]
    muted_ids: frozenset[UUID]


@frozen
class _ClassifiedError:
    user_message: str
    is_transient: bool


def _classify_error(error: Exception) -> _ClassifiedError:
    """The same rules the logs source applies: infrastructure trouble is transient and holds the
    failure counter; a query the user can fix is not."""
    if isinstance(error, ValueError):
        # The metrics facade raises ValueError for a request it refuses (span, interval,
        # quantile). That text is ours, so it is safe to show.
        return _ClassifiedError(user_message=str(error)[:500], is_transient=False)
    category = classify_query_error(error)
    if category == QueryErrorCategory.RATE_LIMITED:
        return _ClassifiedError(
            user_message="PostHog is temporarily busy. The alert check will retry automatically.", is_transient=True
        )
    if category == QueryErrorCategory.QUERY_PERFORMANCE_ERROR:
        return _ClassifiedError(
            user_message="Query is too expensive. Try narrower filters or a shorter window.", is_transient=False
        )
    if category == QueryErrorCategory.USER_ERROR and isinstance(error, ExposedCHQueryError | ExposedHogQLError):
        return _ClassifiedError(user_message=str(error)[:500], is_transient=False)
    if category == QueryErrorCategory.CANCELLED:
        return _ClassifiedError(
            user_message="Alert check was cancelled. It will retry automatically.", is_transient=True
        )
    return _ClassifiedError(
        user_message="Alert check failed unexpectedly. PostHog has been notified.", is_transient=True
    )


def _record_check_metrics(
    check: PlatformAlertCheckInput,
    *,
    new_state: str,
    notification: NotificationAction,
    muted_notification: NotificationAction = NotificationAction.NONE,
    skip: SkipReason | None = None,
    muted_by_quiet_hours: bool = False,
    now: datetime,
) -> None:
    source = SourceKind.METRICS.value
    safe_record(increment_checks, source, notification.value)
    if skip is not None:
        safe_record(increment_checks_skipped, source, skip.value)
    if muted_notification != NotificationAction.NONE:
        mute_reason = MuteReason.QUIET_HOURS if muted_by_quiet_hours else MuteReason.SNOOZE
        safe_record(increment_notifications_muted, source, mute_reason.value)
    if check.state != new_state:
        safe_record(increment_state_transition, source, check.state, new_state)
    if check.next_check_at is not None:
        lag_ms = int((now - check.next_check_at).total_seconds() * 1000)
        if lag_ms > 0:
            safe_record(record_scheduler_lag, source, lag_ms)


def _verdict(
    check: PlatformAlertCheckInput,
    check_input: CheckInput,
    prior_breached: tuple[bool, ...],
    *,
    now: datetime,
    skip: SkipReason | None,
) -> AlertCheckOutcome:
    outcome = evaluate_alert_check(_snapshot(check, prior_breached), check_input, now, policy=_POLICY)
    _record_check_metrics(
        check,
        new_state=outcome.new_state.value,
        notification=outcome.notification,
        muted_notification=outcome.muted_notification,
        skip=skip,
        muted_by_quiet_hours=check_input.muted,
        now=now,
    )
    return outcome


def _evaluation_key(check: PlatformAlertCheckInput, window_end: datetime) -> str:
    """Names the scheduled check and the window it answered for, in the logs source's shape.

    The slot is in the key because the window end is clamped to the ingestion checkpoint, so two
    consecutive checks can reach the same window end. Both parts are read before anything is
    written, so a retry recomputes the same key.
    """
    return f"slot:{slot_of(check.next_check_at, window_end)}|window:{window_end.isoformat()}"


def _recorded(
    check: PlatformAlertCheckInput,
    *,
    outcome: Outcome,
    evaluation_key: str,
    kind: AlertEventKind,
    notified: bool,
    now: datetime,
    value: float | None = None,
    error_message: str | None = None,
    muted_notification: str = "",
    disable: bool = False,
) -> PlatformAlertOutcome:
    """The one place a recorded outcome is built, so every path states the firing the same way."""
    return PlatformAlertOutcome(
        configuration_id=check.id,
        evaluation_key=evaluation_key,
        kind=kind,
        new_state=outcome.new_state.value,
        notified=notified,
        consecutive_failures=outcome.consecutive_failures,
        firing_episode=decide_firing_episode(_snapshot(check, ()), outcome, now, policy=_POLICY),
        value=value,
        error_message=error_message,
        muted_notification=muted_notification,
        disable=disable,
    )


def _decided(
    check: PlatformAlertCheckInput,
    outcome: AlertCheckOutcome,
    *,
    window_end: datetime,
    now: datetime,
    value: float | None = None,
) -> Decision:
    return _recorded(
        check,
        outcome=outcome,
        evaluation_key=_evaluation_key(check, window_end),
        kind=NOTIFICATION_EVENT_KINDS[outcome.notification],
        notified=outcome.update_last_notified_at,
        now=now,
        value=value,
        error_message=outcome.error_message,
        muted_notification=(
            "" if outcome.muted_notification == NotificationAction.NONE else outcome.muted_notification.value
        ),
        disable=outcome.disable,
    )


def _select_series(series: Sequence[MetricSeries], source: MetricsAlertSource) -> MetricSeries:
    wanted = source.evaluated_clause()
    matching = [s for s in series if s.clause == wanted]
    if not matching:
        raise ValueError(f"the query returned no series for clause {wanted!r}")
    if len(matching) > 1:
        # One state per configuration until grouped alerts land; a grouped result cannot be
        # collapsed into it without hiding a breaching series behind a recovering one.
        raise ValueError("grouped metrics alerts are not supported yet; remove group_by from the clause")
    return matching[0]


def _evaluate_one(
    check: PlatformAlertCheckInput,
    series: Sequence[MetricSeries],
    source: MetricsAlertSource,
    *,
    now: datetime,
    muted: bool,
    window_end: datetime,
) -> tuple[AlertCheckOutcome, float | None]:
    """The verdict, and the current window's value for the history row."""
    condition = source.condition
    values = _values_newest_first(
        _select_series(series, source),
        check.evaluation_periods,
        window_end=window_end,
        window=timedelta(minutes=condition.window_minutes),
    )
    flags = tuple(_breached(value, condition.threshold_count, condition.threshold_operator) for value in values)
    current, *prior = flags
    if current is None:
        # No value for the current window is not a clear window: the alert keeps its state and
        # its failure count, and announces nothing.
        outcome = _verdict(
            check, CheckInput(threshold_breached=False, is_inconclusive=True, muted=muted), (), now=now, skip=None
        )
        return outcome, None
    outcome = _verdict(
        check,
        CheckInput(threshold_breached=current, muted=muted),
        tuple(bool(flag) for flag in prior),
        now=now,
        skip=None,
    )
    return outcome, values[0]


def _failed(check: PlatformAlertCheckInput, error: Exception, *, now: datetime, muted: bool) -> AlertCheckOutcome:
    classified = _classify_error(error)
    return _verdict(
        check,
        CheckInput(
            threshold_breached=False,
            error_message=classified.user_message,
            is_transient_error=classified.is_transient,
            muted=muted,
        ),
        (),
        now=now,
        skip=SkipReason.QUERY_FAILED,
    )


def _held(
    check: PlatformAlertCheckInput,
    outcome: ControlPlaneOutcome,
    *,
    skip: SkipReason,
    now: datetime,
    error_message: str,
) -> Decision:
    """A control-plane transition the check machine cannot express. The outcome advances the schedule."""
    _record_check_metrics(
        check, new_state=outcome.new_state.value, notification=NotificationAction.NONE, skip=skip, now=now
    )
    return _recorded(
        check,
        outcome=outcome,
        evaluation_key=_evaluation_key(check, now),
        # The notification is NONE here only because the check machine never ran.
        kind=AlertEventKind.BROKEN,
        notified=False,
        now=now,
        error_message=error_message,
    )


def _evaluate_check(
    team: Team,
    check: PlatformAlertCheckInput,
    checkpoint: datetime | None,
    *,
    now: datetime,
    query_seconds: int,
    muted: bool,
) -> Decision:
    # Triage already parsed it, so this cannot raise.
    source = parse_source(check.source_config)
    # The last complete bucket at or before the due time, so a due time or a checkpoint inside a bucket
    # never evaluates a partial window.
    date_to = _align_to_interval(
        resolve_alert_date_to(check.next_check_at or now, checkpoint),
        WINDOW_TO_INTERVAL[source.condition.window_minutes],
        tzinfo=team.timezone_info,
    )
    value: float | None = None
    try:
        series = run_metric_query(
            team=team,
            request=_request(source, check, date_to),
            query_settings=HogQLGlobalSettings(
                # Every clause is its own query, so the cap is split so the whole check stays under it.
                max_execution_time=max(1, query_seconds // len(source.clauses)),
                # A partial result could resolve an alert that is breaching, so a slow query fails.
                timeout_overflow_mode="throw",
            ),
            # Alerts read no unit, and the lookup would be one more query outside the split cap.
            include_units=False,
        )
        outcome, value = _evaluate_one(check, series, source, now=now, muted=muted, window_end=date_to)
    except Exception as error:
        logger.exception("Failed to evaluate a metrics alert", check_id=str(check.id), error=str(error))
        outcome = _failed(check, error, now=now, muted=muted)
    return _decided(check, outcome, window_end=date_to, now=now, value=value)


def _triage(checks: Sequence[PlatformAlertCheckInput], *, now: datetime, tz_name: str) -> _Triage:
    """Splits a batch into the checks a query can answer, the ones already decided, and the muted.

    A skip is a decision, not an omission: dropping a check records nothing, so its due time stays
    where it was and discovery hands it back on every tick, forever.
    """
    decided: list[Decision] = []
    evaluable: list[PlatformAlertCheckInput] = []
    muted_ids: set[UUID] = set()
    for check in checks:
        broken_reason = _broken_reason(check)
        if broken_reason is not None:
            logger.warning(
                "Marking a metrics alert BROKEN for a configuration no query can answer",
                check_id=str(check.id),
                reason=broken_reason,
            )
            decided.append(
                _held(
                    check,
                    apply_broken_config(_snapshot(check, ())),
                    skip=SkipReason.BROKEN_CONFIG,
                    now=now,
                    error_message=broken_reason,
                )
            )
            continue
        if _is_in_quiet_hours(check, now, tz_name):
            muted_ids.add(check.id)
        evaluable.append(check)
    return _Triage(decided=decided, evaluable=evaluable, muted_ids=frozenset(muted_ids))


def _collect(decided: Sequence[Decision], started_at: float) -> SourceBatchEvaluation:
    safe_record(record_batch_duration, SourceKind.METRICS.value, int((time.monotonic() - started_at) * 1000))
    return SourceBatchEvaluation(outcomes=tuple(decided), deliveries=())


def evaluate_metrics_batch(team_id: int, slot: str, cutoff: datetime) -> SourceBatchEvaluation:
    """Evaluates one batch key: a team's metrics alerts due in one minute, against the tick's cutoff.

    `cutoff` is the tick occasion, not the clock, so a retried attempt evaluates the same alerts
    against the same windows and derives the same evaluation keys. Writes nothing.
    """
    started_at = time.monotonic()
    checks = due_checks(team_id, SourceKind.METRICS.value, slot, cutoff)
    if not checks:
        return SourceBatchEvaluation(outcomes=(), deliveries=())

    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return SourceBatchEvaluation(outcomes=(), deliveries=())

    triage = _triage(checks, now=cutoff, tz_name=team.timezone)
    if not triage.evaluable:
        return _collect(triage.decided, started_at)
    decided = list(triage.decided)

    try:
        checkpoint = fetch_live_metrics_checkpoint(team)
    except Exception as error:
        logger.exception("Failed to fetch metrics ingestion checkpoint; falling back to the due time", error=str(error))
        checkpoint = None

    deadline = started_at + BATCH_QUERY_BUDGET_SECONDS
    unqueried = 0
    for check in triage.evaluable:
        query_seconds = min(MAX_QUERY_SECONDS, int(deadline - time.monotonic()))
        if query_seconds < MIN_QUERY_SECONDS:
            # No outcome, deliberately: a check that was never asked keeps its due time.
            unqueried += 1
            continue
        decided.append(
            _evaluate_check(
                team,
                check,
                checkpoint,
                now=cutoff,
                query_seconds=query_seconds,
                muted=check.id in triage.muted_ids,
            )
        )

    if unqueried:
        logger.warning(
            "Left metrics alerts unqueried on the batch query budget",
            team_id=team_id,
            slot=slot,
            unqueried=unqueried,
            budget_seconds=BATCH_QUERY_BUDGET_SECONDS,
        )
    return _collect(decided, started_at)
