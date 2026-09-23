"""Evaluation of due logs alerts on the shared alerts platform.

Reads a batch of checks from the shared platform and reports what it decided. The logs
product's own tables are never touched: the production logs fleet evaluates the same alerts
against `LogsAlertConfiguration` on its own queue, so the two stacks keep separate state and
neither can notify on the other's behalf. Delivery stops at a recorded preview.

This reads and decides; it writes nothing. The platform records the batch in its own activity,
after Temporal has the deliveries this returned, so an attempt that dies mid-flight costs its
queries and nothing else.

Cohorting and query execution reuse the production helpers, so an evaluation says what the
logs stack would have said given the same configuration. The lifecycle decision comes from
the shared machine configured with this source's policy, not from the logs product.
"""

import time
from collections.abc import Sequence
from datetime import datetime, timedelta
from itertools import batched

import structlog

from posthog.models import Team

from products.alerts.backend.facade.contracts import (
    AlertDeliveryPreview,
    AlertEventKind,
    CheckOutcomeReason,
    GroupTransition,
    PlatformAlertCheckInput,
    PlatformAlertOutcome,
    SourceBatchEvaluation,
    SourceKind,
)
from products.alerts.backend.facade.destinations import list_active_alert_destinations
from products.alerts.backend.facade.lifecycle import (
    LOGS_ALERT_POLICY,
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
    increment_state_transition,
    record_batch_duration,
    record_scheduler_lag,
    safe_record,
)
from products.alerts.backend.facade.scheduling import (
    is_local_minute_blocked,
    local_minute_of,
    parse_blocked_windows_tuples,
)
from products.logs.backend.alert_check_query import (
    BatchedAlertCheckQuery,
    BucketedCount,
    fetch_live_logs_checkpoint,
    is_projection_eligible,
    resolve_alert_date_to,
    rolling_check_lookback_minutes,
)
from products.logs.backend.alert_destinations import EVENT_KIND_CONFIG, EventKind
from products.logs.backend.alert_error_classifier import classify as classify_alert_error

# Private to the production activity. Reimplementing either would let this path drift from
# what the logs stack evaluates. Promoting them to a shared home is the deeper fix.
from products.logs.backend.temporal.activities import _derive_breaches, _detect_broken_filter_config
from products.logs.backend.temporal.constants import MAX_ALERT_COHORT_SIZE

logger = structlog.get_logger(__name__)

# A fleet-wide burst would otherwise return one activity payload over Temporal's ~2 MiB limit,
# which fails the whole batch rather than truncating it. The bound drops an outcome along with
# the preview it belongs to, so a breach this batch cannot announce keeps its due time.
MAX_PREVIEWS_PER_CYCLE = 500

# Cohorts run one after another, and the production runner measures about four seconds each. A
# higher bound spends the query budget below and returns fewer cohorts, not more; a cohort left
# out keeps its due time.
MAX_COHORTS_PER_CYCLE = 4

# The batch's ClickHouse time, which `EVALUATE_START_TO_CLOSE` in the workflow sits above, so an
# overrunning query is ended by ClickHouse rather than by the activity. It bounds the cohort
# queries only: the per-alert destination lookups below are not inside it.
BATCH_QUERY_BUDGET_SECONDS = 25
# No single cohort query may spend the whole batch budget, or the first slow one starves the rest.
MAX_QUERY_SECONDS = 20
# Below this there is no point starting another query; the cohort keeps its due time instead.
MIN_QUERY_SECONDS = 2

_NOTIFICATION_EVENT_KINDS: dict[NotificationAction, EventKind] = {
    NotificationAction.FIRE: "firing",
    NotificationAction.RESOLVE: "resolved",
    NotificationAction.ERROR: "errored",
    NotificationAction.BROKEN: "broken",
}

# A check that announced nothing is a CHECK even when it moved the alert; the row's two
# states carry the move.
_NOTIFICATION_OUTCOME_KINDS: dict[NotificationAction, AlertEventKind] = {
    NotificationAction.NONE: AlertEventKind.CHECK,
    NotificationAction.FIRE: AlertEventKind.FIRING,
    NotificationAction.RESOLVE: AlertEventKind.RESOLVED,
    NotificationAction.ERROR: AlertEventKind.ERRORED,
    NotificationAction.BROKEN: AlertEventKind.BROKEN,
}


def _evaluation_key(window_end: datetime) -> str:
    """Names the window a check answered for.

    Scoped to the alert by the unique constraint on the row rather than by the string, so the
    key stays the same shape for every source and a retry recomputes it from the batch cutoff.
    """
    return f"window:{window_end.isoformat()}"


def _cohort_key(check: PlatformAlertCheckInput, checkpoint: datetime | None, now: datetime) -> tuple:
    return (
        check.window_minutes,
        check.evaluation_periods,
        check.check_interval_minutes,
        is_projection_eligible(check.source_config),
        resolve_alert_date_to(check.next_check_at or now, checkpoint),
    )


def _is_in_quiet_hours(check: PlatformAlertCheckInput, local_minute: int) -> bool:
    """True when the alert's schedule restriction blocks a check at the batch's local minute."""
    try:
        windows = parse_blocked_windows_tuples(check.schedule_restriction)
        return windows is not None and is_local_minute_blocked(local_minute, windows)
    except Exception as error:
        # A restriction we cannot parse must not decide the alert either way, so the check
        # proceeds and the production stack keeps ownership of the broken configuration.
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
    )


Decision = tuple[PlatformAlertOutcome, AlertDeliveryPreview | None]


def _record_check_metrics(
    check: PlatformAlertCheckInput,
    new_state: str,
    notification: NotificationAction,
    reason: CheckOutcomeReason,
    now: datetime,
) -> None:
    safe_record(increment_checks, SourceKind.LOGS.value, notification.value)
    if reason != CheckOutcomeReason.EVALUATED:
        safe_record(increment_checks_skipped, SourceKind.LOGS.value, reason)
    if check.state != new_state:
        safe_record(increment_state_transition, SourceKind.LOGS.value, check.state, new_state)
    if check.next_check_at is not None:
        lag_ms = int((now - check.next_check_at).total_seconds() * 1000)
        if lag_ms > 0:
            safe_record(record_scheduler_lag, SourceKind.LOGS.value, lag_ms)


def _decide(
    check: PlatformAlertCheckInput,
    check_input: CheckInput,
    prior_breached: tuple[bool, ...],
    *,
    window_end: datetime,
    now: datetime,
    reason: CheckOutcomeReason,
    value: float | None = None,
    query_duration_ms: int | None = None,
) -> Decision:
    """Runs one check through the shared machine and turns its verdict into a delivery.

    `LOGS_ALERT_POLICY` is how the shared machine expresses this source's semantics, so the
    decision is the one the logs stack reaches without routing through the logs product.
    """
    outcome = evaluate_alert_check(_snapshot(check, prior_breached), check_input, now, policy=LOGS_ALERT_POLICY)
    evaluation_key = _evaluation_key(window_end)
    recorded = PlatformAlertOutcome(
        configuration_id=check.id,
        evaluation_key=evaluation_key,
        kind=_NOTIFICATION_OUTCOME_KINDS[outcome.notification],
        new_state=outcome.new_state.value,
        notified=outcome.update_last_notified_at,
        consecutive_failures=outcome.consecutive_failures,
        value=value,
        error_message=check_input.error_message,
        query_duration_ms=query_duration_ms,
        disable=outcome.disable,
    )
    _record_check_metrics(check, outcome.new_state.value, outcome.notification, reason, now)
    if outcome.notification == NotificationAction.NONE:
        return recorded, None

    spec = EVENT_KIND_CONFIG[_NOTIFICATION_EVENT_KINDS[outcome.notification]]
    destinations = list_active_alert_destinations(
        team_id=check.team_id,
        alert_id=str(check.legacy_configuration_id or check.id),
        allowed_event_ids=[spec.event_id],
    )
    return recorded, AlertDeliveryPreview(
        source=SourceKind.LOGS,
        alert_id=str(check.id),
        alert_name=check.name,
        evaluation_key=evaluation_key,
        destination_names=tuple(destination.name for destination in destinations),
        # One transition with an empty grouping key. Logs does not group yet, and delivery
        # reads a list either way, so fan-out changes this call and nothing downstream.
        transitions=(GroupTransition(grouping_key="", notification=outcome.notification.value),),
    )


def _evaluate_one(
    check: PlatformAlertCheckInput,
    buckets: list[BucketedCount],
    *,
    window_end: datetime,
    now: datetime,
    query_duration_ms: int | None = None,
) -> Decision:
    current_breached, *prior_windows_breached = _derive_breaches(
        buckets, check.threshold_count, check.threshold_operator, check.evaluation_periods
    ) or (False,)
    # ClickHouse emits no bucket for an empty window, so no buckets is a measured zero.
    return _decide(
        check,
        CheckInput(threshold_breached=current_breached),
        tuple(prior_windows_breached),
        window_end=window_end,
        now=now,
        reason=CheckOutcomeReason.EVALUATED,
        value=float(buckets[-1].count) if buckets else 0.0,
        query_duration_ms=query_duration_ms,
    )


def _failed(check: PlatformAlertCheckInput, error: Exception, *, window_end: datetime, now: datetime) -> Decision:
    """A check that could not reach a verdict, as the shared machine's error path sees it.

    The machine raises `consecutive_failures` and escalates to BROKEN, so an alert that fails
    every check stops being evaluated instead of failing forever. A transient error is classified
    as one so the policy can hold the counter.
    """
    classified = classify_alert_error(error)
    return _decide(
        check,
        CheckInput(
            threshold_breached=False,
            error_message=classified.user_message,
            is_transient_error=classified.is_transient,
        ),
        (),
        window_end=window_end,
        now=now,
        reason=CheckOutcomeReason.QUERY_FAILED,
    )


def _held(
    check: PlatformAlertCheckInput, outcome: ControlPlaneOutcome, *, reason: CheckOutcomeReason, now: datetime
) -> Decision:
    """A control-plane transition the check machine cannot express. The outcome advances the schedule."""
    recorded = PlatformAlertOutcome(
        configuration_id=check.id,
        evaluation_key=_evaluation_key(now),
        # The notification is NONE here only because the check machine never ran.
        kind=AlertEventKind.BROKEN,
        new_state=outcome.new_state.value,
        notified=False,
        consecutive_failures=outcome.consecutive_failures,
    )
    _record_check_metrics(check, outcome.new_state.value, NotificationAction.NONE, reason, now)
    return recorded, None


def _evaluate_cohort(
    team: Team, checks: Sequence[PlatformAlertCheckInput], key: tuple, *, now: datetime, query_seconds: int
) -> list[Decision]:
    window_minutes, evaluation_periods, cadence_minutes, projection_eligible, date_to = key
    lookback = rolling_check_lookback_minutes(window_minutes, cadence_minutes, evaluation_periods)

    query_started_at = time.monotonic()
    try:
        result = BatchedAlertCheckQuery(
            team=team,
            alerts=checks,
            date_from=date_to - timedelta(minutes=lookback),
            date_to=date_to,
            projection_eligible=projection_eligible,
            max_execution_time=query_seconds,
        ).execute_rolling_checks(date_to, window_minutes, cadence_minutes, evaluation_periods)
    except Exception as error:
        # One cohort's query must not end the batch, which is how the production cohort runner
        # contains the same failure.
        logger.exception(
            "Logs alert cohort query failed",
            team_id=team.id,
            cohort_size=len(checks),
            error=str(error),
        )
        # Deliberately not caught per check below. A check dropped there carries no outcome, so the
        # batch would advance every other check's schedule and leave this one due with its failure
        # counter unmoved, never reaching the escalation that stops it.
        return [_failed(check, error, window_end=date_to, now=now) for check in checks]

    # One query serves the cohort, so every check in it records the same duration.
    query_duration_ms = int((time.monotonic() - query_started_at) * 1000)

    decided: list[Decision] = []
    for check in checks:
        try:
            decided.append(
                _evaluate_one(
                    check,
                    result.per_alert.get(str(check.id), []),
                    window_end=date_to,
                    now=now,
                    query_duration_ms=query_duration_ms,
                )
            )
        except Exception as error:
            logger.exception("Failed to evaluate a logs alert", check_id=str(check.id), error=str(error))
            decided.append(_failed(check, error, window_end=date_to, now=now))
    return decided


def _triage(
    checks: Sequence[PlatformAlertCheckInput], team: Team, *, now: datetime
) -> tuple[list[Decision], list[PlatformAlertCheckInput]]:
    """Splits a batch into the checks a query can answer and the ones already decided.

    A skip is a decision, not an omission. Dropping one records nothing, so its due time stays
    where it was and discovery hands the same check back on the next tick, forever.
    """
    # One conversion for the batch: every check shares the tick instant and the team's timezone.
    local_minute = local_minute_of(now, team.timezone)
    decided: list[Decision] = []
    evaluable: list[PlatformAlertCheckInput] = []
    for check in checks:
        broken_reason = _detect_broken_filter_config(check.source_config)
        if broken_reason is not None:
            logger.warning(
                "Marking a logs alert BROKEN for an invalid filter config",
                check_id=str(check.id),
                reason=broken_reason,
            )
            decided.append(
                _held(
                    check,
                    apply_broken_config(_snapshot(check, ())),
                    reason=CheckOutcomeReason.BROKEN_CONFIG,
                    now=now,
                )
            )
            continue
        if _is_in_quiet_hours(check, local_minute):
            # Through the machine as an inconclusive check, so the state and the failure counter
            # come from the one place allowed to decide them.
            decided.append(
                _decide(
                    check,
                    CheckInput(threshold_breached=False, is_inconclusive=True),
                    (),
                    window_end=now,
                    now=now,
                    reason=CheckOutcomeReason.QUIET_HOURS,
                )
            )
            continue
        evaluable.append(check)
    return decided, evaluable


def _collect(decided: Sequence[Decision], team_id: int, slot: str, started_at: float) -> SourceBatchEvaluation:
    """Applies the payload bound and reports the batch."""
    outcomes: list[PlatformAlertOutcome] = []
    previews: list[AlertDeliveryPreview] = []
    omitted = 0
    for outcome, preview in decided:
        if preview is not None and len(previews) >= MAX_PREVIEWS_PER_CYCLE:
            omitted += 1
            continue
        outcomes.append(outcome)
        if preview is not None:
            previews.append(preview)

    if omitted:
        logger.warning(
            "Deferred logs alert deliveries over the batch payload bound",
            team_id=team_id,
            slot=slot,
            delivered=len(previews),
            deferred=omitted,
        )
        safe_record(increment_deliveries_deferred, SourceKind.LOGS.value, omitted)
    safe_record(record_batch_duration, SourceKind.LOGS.value, int((time.monotonic() - started_at) * 1000))
    return SourceBatchEvaluation(outcomes=tuple(outcomes), previews=tuple(previews), omitted=omitted)


def evaluate_logs_batch(team_id: int, slot: str, cutoff: datetime) -> SourceBatchEvaluation:
    """Evaluates one batch key: a team's alerts due in one minute, against the tick's cutoff.

    The dispatcher passes the key rather than a list of ids, so the set is read here and is the
    fresher one. `cutoff` is the tick occasion, not the clock, so a retried attempt evaluates
    the same alerts against the same windows and derives the same evaluation keys.

    Writes nothing, which is what lets an attempt be retried: the alerts stay due, so the second
    attempt reads the same batch and reaches the same decisions.
    """
    started_at = time.monotonic()
    checks = due_checks(team_id, SourceKind.LOGS.value, slot, cutoff)
    if not checks:
        return SourceBatchEvaluation(outcomes=(), previews=())

    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return SourceBatchEvaluation(outcomes=(), previews=())

    decided, evaluable = _triage(checks, team, now=cutoff)
    if not evaluable:
        # Returns before the checkpoint query below, which nothing left would use.
        return _collect(decided, team_id, slot, started_at)

    # One checkpoint for the pass, matching the production discovery activity. A failure falls
    # back to wall-clock rather than ending the batch.
    try:
        checkpoint = fetch_live_logs_checkpoint(team)
    except Exception as error:
        logger.exception("Failed to fetch logs ingestion checkpoint; falling back to wall-clock", error=str(error))
        checkpoint = None

    cohorts: dict[tuple, list[PlatformAlertCheckInput]] = {}
    for check in evaluable:
        cohorts.setdefault(_cohort_key(check, checkpoint, cutoff), []).append(check)

    if len(cohorts) > MAX_COHORTS_PER_CYCLE:
        logger.warning(
            "Truncating logs alert cohorts to keep the batch inside its activity timeout",
            produced=len(cohorts),
            evaluated=MAX_COHORTS_PER_CYCLE,
        )

    deadline = started_at + BATCH_QUERY_BUDGET_SECONDS
    unqueried = 0
    # Capped the way the production cohort query requires: one batched query carries one countIf
    # column per alert, so an uncapped cohort is an unbounded query.
    chunks = [
        (cohort_key, list(chunk))
        for cohort_key, cohort in list(cohorts.items())[:MAX_COHORTS_PER_CYCLE]
        for chunk in batched(cohort, MAX_ALERT_COHORT_SIZE, strict=False)
    ]
    for cohort_key, chunk in chunks:
        query_seconds = min(MAX_QUERY_SECONDS, int(deadline - time.monotonic()))
        if query_seconds < MIN_QUERY_SECONDS:
            # No outcome, deliberately. A skipped check was decided; these were never asked, so
            # advancing their schedule would drop a real check. They keep their due time.
            unqueried += len(chunk)
            continue
        decided.extend(_evaluate_cohort(team, chunk, cohort_key, now=cutoff, query_seconds=query_seconds))

    if unqueried:
        logger.warning(
            "Left logs alert cohorts unqueried on the batch query budget",
            team_id=team_id,
            slot=slot,
            unqueried=unqueried,
            budget_seconds=BATCH_QUERY_BUDGET_SECONDS,
        )
    return _collect(decided, team_id, slot, started_at)
