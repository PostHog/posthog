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

import time
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.errors import ExposedHogQLError

from posthog.dataclasses import frozen
from posthog.errors import ExposedCHQueryError, QueryErrorCategory, classify_query_error
from posthog.models import Team

from products.alerts.backend.facade.contracts import (
    MAX_GROUPS_PER_CONFIGURATION,
    AlertDeliveryPreview,
    GroupTransition,
    MuteReason,
    PlatformAlertCheckInput,
    PlatformAlertGroupState,
    PlatformAlertOutcome,
    SkipReason,
    SourceBatchEvaluation,
    SourceKind,
    grouping_key_for,
)
from products.alerts.backend.facade.lifecycle import (
    PLATFORM_LOGS_ALERT_POLICY,
    AlertCheckOutcome,
    AlertSnapshot,
    AlertState,
    CheckInput,
    ControlPlaneOutcome,
    NotificationAction,
    apply_broken_config,
    evaluate_alert_check,
)
from products.alerts.backend.facade.platform_alerts import due_checks
from products.alerts.backend.facade.platform_metrics import (
    increment_checks,
    increment_checks_skipped,
    increment_deliveries_deferred,
    increment_notifications_muted,
    increment_state_transition,
    record_batch_duration,
    record_scheduler_lag,
    safe_record,
)
from products.alerts.backend.facade.scheduling import is_utc_datetime_blocked, parse_blocked_windows_tuples
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
# A fleet-wide burst would otherwise return one payload over Temporal's ~2 MiB limit.
MAX_PREVIEWS_PER_CYCLE = 500
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


class MetricsAlertSource(BaseModel):
    """The `source_config` of a `source_kind="metrics"` configuration."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["MetricsAlertSource"] = "MetricsAlertSource"
    clauses: list[MetricsAlertClause] = Field(min_length=1, max_length=MAX_CLAUSES_PER_QUERY)
    formula: str | None = None
    value_clause: str | None = None

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
    if check.window_minutes not in WINDOW_TO_INTERVAL:
        return f"unsupported window of {check.window_minutes} minutes"
    if source.formula is None and source.value_clause is not None:
        if source.value_clause not in {clause.name for clause in source.clauses}:
            return f"value clause {source.value_clause!r} is not one of the clauses"
    return None


def _request(source: MetricsAlertSource, check: PlatformAlertCheckInput, date_to: datetime) -> MetricQueryRequest:
    # Contiguous windows: N-of-M reads the newest `evaluation_periods` buckets of one query, so no
    # history table is needed and a retry reads the same buckets.
    lookback = timedelta(minutes=check.window_minutes * check.evaluation_periods)
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
        interval=WINDOW_TO_INTERVAL[check.window_minutes],
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


def _breached(value: float | None, threshold_count: int, threshold_operator: str) -> bool | None:
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


def _root_group(check: PlatformAlertCheckInput) -> PlatformAlertGroupState:
    return PlatformAlertGroupState(
        grouping_key="", state=check.state, last_notified_at=check.last_notified_at, snooze_until=check.snooze_until
    )


def _group_of(check: PlatformAlertCheckInput, grouping_key: str) -> PlatformAlertGroupState:
    """The runtime state of one label set. A label set seen for the first time starts not firing.

    A snooze on the root row is the configuration's snooze, so every group inherits it: a person
    who mutes the alert mutes all of its services.
    """
    if grouping_key == "":
        return _root_group(check)
    root_snooze = check.snooze_until
    for group in check.groups:
        if group.grouping_key == grouping_key:
            return replace(group, snooze_until=group.snooze_until or root_snooze)
    return PlatformAlertGroupState(
        grouping_key=grouping_key, state="not_firing", last_notified_at=None, snooze_until=root_snooze
    )


def _snapshot(
    check: PlatformAlertCheckInput, group: PlatformAlertGroupState, prior_breached: tuple[bool, ...]
) -> AlertSnapshot:
    return AlertSnapshot(
        state=AlertState(group.state),
        cooldown=timedelta(minutes=check.cooldown_minutes),
        last_notified_at=group.last_notified_at,
        snooze_until=group.snooze_until,
        consecutive_failures=check.consecutive_failures,
        evaluation_periods=check.evaluation_periods,
        datapoints_to_alarm=check.datapoints_to_alarm,
        recent_events_breached=prior_breached,
    )


@frozen
class _GroupDecision:
    """What one label set of a configuration decided."""

    group: PlatformAlertGroupState
    labels: dict[str, str]
    value: float | None
    outcome: AlertCheckOutcome
    # A group the query did not answer this cycle. Its outcome carries no verdict on the
    # configuration's health, so it must not decide the failure counter.
    inconclusive: bool = False


# Every outcome a configuration produced this cycle, and what delivery would announce for them.
Decision = tuple[tuple[PlatformAlertOutcome, ...], AlertDeliveryPreview | None]


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
    group: PlatformAlertGroupState,
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
    if group.state != new_state:
        safe_record(increment_state_transition, source, group.state, new_state)
    if check.next_check_at is not None:
        lag_ms = int((now - check.next_check_at).total_seconds() * 1000)
        if lag_ms > 0:
            safe_record(record_scheduler_lag, source, lag_ms)


def _verdict(
    check: PlatformAlertCheckInput,
    group: PlatformAlertGroupState,
    check_input: CheckInput,
    prior_breached: tuple[bool, ...],
    *,
    now: datetime,
    skip: SkipReason | None,
) -> AlertCheckOutcome:
    outcome = evaluate_alert_check(_snapshot(check, group, prior_breached), check_input, now, policy=_POLICY)
    _record_check_metrics(
        check,
        group,
        new_state=outcome.new_state.value,
        notification=outcome.notification,
        muted_notification=outcome.muted_notification,
        skip=skip,
        muted_by_quiet_hours=check_input.muted,
        now=now,
    )
    return outcome


def _recorded(
    check: PlatformAlertCheckInput,
    *,
    grouping_key: str,
    new_state: str,
    notified: bool,
    consecutive_failures: int,
    disable: bool = False,
) -> PlatformAlertOutcome:
    return PlatformAlertOutcome(
        configuration_id=check.id,
        new_state=new_state,
        notified=notified,
        consecutive_failures=consecutive_failures,
        disable=disable,
        grouping_key=grouping_key,
    )


def _delivery(check: PlatformAlertCheckInput, decisions: Sequence[_GroupDecision], *, window_end: datetime) -> Decision:
    """What the platform records for every group, and the one preview that announces the groups
    with a notification. One message per configuration is #1264's default fan-in."""
    # The configuration's counter follows the groups the query answered; an inconclusive group
    # repeats the old value and must not keep a cleared failure alive.
    answered = [d for d in decisions if not d.inconclusive]
    failures = max(d.outcome.consecutive_failures for d in answered) if answered else check.consecutive_failures
    outcomes = tuple(
        _recorded(
            check,
            grouping_key=decision.group.grouping_key,
            new_state=decision.outcome.new_state.value,
            notified=decision.outcome.update_last_notified_at,
            consecutive_failures=failures if decision.inconclusive else decision.outcome.consecutive_failures,
            disable=decision.outcome.disable,
        )
        for decision in decisions
    )
    transitions = tuple(
        GroupTransition(
            grouping_key=decision.group.grouping_key,
            notification=decision.outcome.notification.value,
            labels=decision.labels,
            value=decision.value,
        )
        for decision in decisions
        if decision.outcome.notification != NotificationAction.NONE
    )
    if not transitions:
        return outcomes, None
    return outcomes, AlertDeliveryPreview(
        source=SourceKind.METRICS,
        alert_id=str(check.id),
        alert_name=check.name,
        evaluation_key=f"{check.id}:window:{window_end.isoformat()}",
        # A metrics platform configuration owns no HogFunction destinations yet. Native delivery
        # resolves destinations from the configuration when it lands.
        destination_names=(),
        transitions=transitions,
    )


def _select_series(series: Sequence[MetricSeries], source: MetricsAlertSource) -> list[MetricSeries]:
    wanted = source.evaluated_clause()
    matching = [s for s in series if s.clause == wanted]
    if not matching:
        raise ValueError(f"the query returned no series for clause {wanted!r}")
    return sorted(matching, key=lambda s: grouping_key_for(s.labels))


def _evaluate_group(
    check: PlatformAlertCheckInput,
    group: PlatformAlertGroupState,
    values: tuple[float | None, ...],
    *,
    now: datetime,
    muted: bool,
) -> AlertCheckOutcome:
    flags = tuple(_breached(value, check.threshold_count, check.threshold_operator) for value in values)
    current, *prior = flags
    if current is None:
        # No value for the current window is not a clear window: the group keeps its state and
        # announces nothing.
        return _verdict(
            check,
            group,
            CheckInput(threshold_breached=False, is_inconclusive=True, muted=muted),
            (),
            now=now,
            skip=None,
        )
    return _verdict(
        check,
        group,
        CheckInput(threshold_breached=current, muted=muted),
        tuple(bool(flag) for flag in prior),
        now=now,
        skip=None,
    )


def _inconclusive(
    check: PlatformAlertCheckInput, group: PlatformAlertGroupState, *, now: datetime, muted: bool
) -> _GroupDecision:
    outcome = _verdict(
        check, group, CheckInput(threshold_breached=False, is_inconclusive=True, muted=muted), (), now=now, skip=None
    )
    return _GroupDecision(group=group, labels={}, value=None, outcome=outcome, inconclusive=True)


def _evaluate_groups(
    check: PlatformAlertCheckInput,
    series: Sequence[MetricSeries],
    source: MetricsAlertSource,
    *,
    now: datetime,
    muted: bool,
    window_end: datetime,
) -> list[_GroupDecision]:
    """One decision per label set the query returned, plus one per label set the platform
    remembers and the query no longer returns. A vanished series is inconclusive for its group
    rather than dropped, so a group that was firing is not stranded."""
    selected = _select_series(series, source)
    grouped = len(selected) > 1 or any(one.labels for one in selected)
    decisions: list[_GroupDecision] = []
    seen: set[str] = set()
    for one in selected[:MAX_GROUPS_PER_CONFIGURATION]:
        key = grouping_key_for(one.labels)
        seen.add(key)
        values = _values_newest_first(
            one, check.evaluation_periods, window_end=window_end, window=timedelta(minutes=check.window_minutes)
        )
        group = _group_of(check, key)
        outcome = _evaluate_group(check, group, values, now=now, muted=muted)
        decisions.append(_GroupDecision(group=group, labels=dict(one.labels), value=values[0], outcome=outcome))
    if len(selected) > MAX_GROUPS_PER_CONFIGURATION:
        # Visible on the root group. Silently stopping at the cap would read as "nothing is wrong"
        # for every label set past it.
        overflow = ValueError(
            f"Too many groups ({len(selected)} > {MAX_GROUPS_PER_CONFIGURATION}); add filters or group by fewer labels"
        )
        decisions.append(_failed(check, _root_group(check), overflow, now=now, muted=muted))
        seen.add("")
    for group in check.groups:
        if group.grouping_key in seen:
            continue
        if group.grouping_key == "" and grouped:
            # The root row of a grouped configuration only carries whole-evaluation failures.
            continue
        decisions.append(_inconclusive(check, group, now=now, muted=muted))
    return decisions


def _failed(
    check: PlatformAlertCheckInput, group: PlatformAlertGroupState, error: Exception, *, now: datetime, muted: bool
) -> _GroupDecision:
    classified = _classify_error(error)
    outcome = _verdict(
        check,
        group,
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
    return _GroupDecision(group=group, labels={}, value=None, outcome=outcome)


def _held(check: PlatformAlertCheckInput, outcome: ControlPlaneOutcome, *, skip: SkipReason, now: datetime) -> Decision:
    recorded = _recorded(
        check,
        grouping_key="",
        new_state=outcome.new_state.value,
        notified=False,
        consecutive_failures=outcome.consecutive_failures,
    )
    _record_check_metrics(
        check,
        _root_group(check),
        new_state=outcome.new_state.value,
        notification=NotificationAction.NONE,
        skip=skip,
        now=now,
    )
    return (recorded,), None


def _evaluate_check(
    team: Team,
    check: PlatformAlertCheckInput,
    checkpoint: datetime | None,
    *,
    now: datetime,
    query_seconds: int,
    muted: bool,
) -> Decision:
    # The last complete bucket at or before the due time, so a due time or a checkpoint inside a bucket
    # never evaluates a partial window.
    date_to = _align_to_interval(
        resolve_alert_date_to(check.next_check_at or now, checkpoint),
        WINDOW_TO_INTERVAL[check.window_minutes],
        tzinfo=team.timezone_info,
    )
    try:
        source = parse_source(check.source_config)
        series = run_metric_query(
            team=team,
            request=_request(source, check, date_to),
            query_settings=HogQLGlobalSettings(
                # Every clause is its own query, so the cap is split so the whole check stays under it.
                max_execution_time=max(1, query_seconds // len(source.clauses)),
                # A partial result could resolve an alert that is breaching, so a slow query fails.
                timeout_overflow_mode="throw",
            ),
        )
        decisions = _evaluate_groups(check, series, source, now=now, muted=muted, window_end=date_to)
    except Exception as error:
        logger.exception("Failed to evaluate a metrics alert", check_id=str(check.id), error=str(error))
        # A failed query fails the whole evaluation, so the root group carries it.
        decisions = [_failed(check, _root_group(check), error, now=now, muted=muted)]
    return _delivery(check, decisions, window_end=date_to)


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
                    apply_broken_config(_snapshot(check, _root_group(check), ())),
                    skip=SkipReason.BROKEN_CONFIG,
                    now=now,
                )
            )
            continue
        if _is_in_quiet_hours(check, now, tz_name):
            muted_ids.add(check.id)
        evaluable.append(check)
    return _Triage(decided=decided, evaluable=evaluable, muted_ids=frozenset(muted_ids))


def _collect(decided: Sequence[Decision], team_id: int, slot: str, started_at: float) -> SourceBatchEvaluation:
    outcomes: list[PlatformAlertOutcome] = []
    previews: list[AlertDeliveryPreview] = []
    omitted = 0
    for group_outcomes, preview in decided:
        if preview is not None and len(previews) >= MAX_PREVIEWS_PER_CYCLE:
            omitted += 1
            continue
        outcomes.extend(group_outcomes)
        if preview is not None:
            previews.append(preview)
    if omitted:
        logger.warning(
            "Deferred metrics alert deliveries over the batch payload bound",
            team_id=team_id,
            slot=slot,
            delivered=len(previews),
            deferred=omitted,
        )
        safe_record(increment_deliveries_deferred, SourceKind.METRICS.value, omitted)
    safe_record(record_batch_duration, SourceKind.METRICS.value, int((time.monotonic() - started_at) * 1000))
    return SourceBatchEvaluation(outcomes=tuple(outcomes), previews=tuple(previews), omitted=omitted)


def evaluate_metrics_batch(team_id: int, slot: str, cutoff: datetime) -> SourceBatchEvaluation:
    """Evaluates one batch key: a team's metrics alerts due in one minute, against the tick's cutoff.

    `cutoff` is the tick occasion, not the clock, so a retried attempt evaluates the same alerts
    against the same windows and derives the same evaluation keys. Writes nothing.
    """
    started_at = time.monotonic()
    checks = due_checks(team_id, SourceKind.METRICS.value, slot, cutoff)
    if not checks:
        return SourceBatchEvaluation(outcomes=(), previews=())

    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return SourceBatchEvaluation(outcomes=(), previews=())

    triage = _triage(checks, now=cutoff, tz_name=team.timezone)
    if not triage.evaluable:
        return _collect(triage.decided, team_id, slot, started_at)
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
    return _collect(decided, team_id, slot, started_at)
