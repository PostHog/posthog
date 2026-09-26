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
from uuid import UUID

import structlog

from posthog.models import Team

from products.alerts.backend.facade.contracts import (
    AlertDeliveryPreview,
    AlertEventKind,
    GroupTransition,
    MuteReason,
    PlatformAlertCheckInput,
    PlatformAlertOutcome,
    SkipReason,
    SourceBatchEvaluation,
    SourceKind,
)
from products.alerts.backend.facade.destinations import list_active_alert_destinations
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


# A check that announced nothing is a CHECK even when it moved the alert; the row's two states
# carry the move.
_NOTIFICATION_OUTCOME_KINDS: dict[NotificationAction, AlertEventKind] = {
    NotificationAction.NONE: AlertEventKind.CHECK,
    NotificationAction.FIRE: AlertEventKind.FIRING,
    NotificationAction.RESOLVE: AlertEventKind.RESOLVED,
    NotificationAction.ERROR: AlertEventKind.ERRORED,
    NotificationAction.BROKEN: AlertEventKind.BROKEN,
}


def _evaluation_key(window_end: datetime) -> str:
    """Names the window a check answered for.

    Scoped to the alert by the row's own columns rather than by the string, so the key keeps one
    shape across sources and a retry recomputes it from the batch cutoff.
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


def _is_in_quiet_hours(check: PlatformAlertCheckInput, now: datetime, tz_name: str) -> bool:
    """True when the alert's schedule restriction mutes an announcement at the batch instant.

    The check still runs, so an incident wholly inside the window is still recorded.
    """
    if not check.schedule_restriction:
        return False
    try:
        return is_utc_datetime_blocked(now, tz_name, parse_blocked_windows_tuples(check.schedule_restriction))
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
    *,
    new_state: str,
    notification: NotificationAction,
    muted_notification: NotificationAction = NotificationAction.NONE,
    skip: SkipReason | None = None,
    muted_by_quiet_hours: bool = False,
    now: datetime,
) -> None:
    safe_record(increment_checks, SourceKind.LOGS.value, notification.value)
    if skip is not None:
        safe_record(increment_checks_skipped, SourceKind.LOGS.value, skip.value)
    if muted_notification != NotificationAction.NONE:
        # The machine owns the snooze predicate, so the source's flag is what separates the two.
        mute_reason = MuteReason.QUIET_HOURS if muted_by_quiet_hours else MuteReason.SNOOZE
        safe_record(increment_notifications_muted, SourceKind.LOGS.value, mute_reason.value)
    if check.state != new_state:
        safe_record(increment_state_transition, SourceKind.LOGS.value, check.state, new_state)
    if check.next_check_at is not None:
        lag_ms = int((now - check.next_check_at).total_seconds() * 1000)
        if lag_ms > 0:
            safe_record(record_scheduler_lag, SourceKind.LOGS.value, lag_ms)


def _verdict(
    check: PlatformAlertCheckInput,
    check_input: CheckInput,
    prior_breached: tuple[bool, ...],
    *,
    now: datetime,
    skip: SkipReason | None,
) -> AlertCheckOutcome:
    """Runs one check through the shared machine.

    `PLATFORM_LOGS_ALERT_POLICY` is how the shared machine expresses this source's semantics. It
    is the logs stack's lifecycle with one difference: a mute holds the announcement rather than
    the check, so a snoozed or schedule-restricted alert still tracks reality.

    Separate from `_delivery` because a caller that catches evaluation errors must not also
    catch a destination lookup. A lookup failure would otherwise be recorded as a failed check
    and raise the alert's failure counter, after a query that succeeded.
    """
    outcome = evaluate_alert_check(
        _snapshot(check, prior_breached), check_input, now, policy=PLATFORM_LOGS_ALERT_POLICY
    )
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


def _recorded(
    check: PlatformAlertCheckInput,
    *,
    evaluation_key: str,
    kind: AlertEventKind,
    new_state: str,
    notified: bool,
    consecutive_failures: int,
    value: float | None = None,
    error_message: str | None = None,
    query_duration_ms: int | None = None,
    muted_notification: str = "",
    disable: bool = False,
) -> PlatformAlertOutcome:
    """The one place a recorded outcome is built, so the evaluated and held paths cannot drift."""
    return PlatformAlertOutcome(
        configuration_id=check.id,
        evaluation_key=evaluation_key,
        kind=kind,
        new_state=new_state,
        notified=notified,
        consecutive_failures=consecutive_failures,
        value=value,
        error_message=error_message,
        query_duration_ms=query_duration_ms,
        muted_notification=muted_notification,
        disable=disable,
    )


def _delivery(
    check: PlatformAlertCheckInput,
    outcome: AlertCheckOutcome,
    *,
    window_end: datetime,
    value: float | None = None,
    query_duration_ms: int | None = None,
) -> Decision:
    """What the platform records for a verdict, and what delivery would announce for it."""
    recorded = _recorded(
        check,
        evaluation_key=_evaluation_key(window_end),
        kind=_NOTIFICATION_OUTCOME_KINDS[outcome.notification],
        new_state=outcome.new_state.value,
        notified=outcome.update_last_notified_at,
        consecutive_failures=outcome.consecutive_failures,
        value=value,
        error_message=outcome.error_message,
        query_duration_ms=query_duration_ms,
        muted_notification=(
            "" if outcome.muted_notification == NotificationAction.NONE else outcome.muted_notification.value
        ),
        disable=outcome.disable,
    )
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
        evaluation_key=f"{check.id}:window:{window_end.isoformat()}",
        destination_names=tuple(destination.name for destination in destinations),
        # One transition with an empty grouping key. Logs does not group yet, and delivery
        # reads a list either way, so fan-out changes this call and nothing downstream.
        transitions=(GroupTransition(grouping_key="", notification=outcome.notification.value),),
    )


def _evaluate_one(
    check: PlatformAlertCheckInput, buckets: list[BucketedCount], *, now: datetime, muted: bool
) -> AlertCheckOutcome:
    current_breached, *prior_windows_breached = _derive_breaches(
        buckets, check.threshold_count, check.threshold_operator, check.evaluation_periods
    ) or (False,)
    return _verdict(
        check,
        CheckInput(threshold_breached=current_breached, muted=muted),
        tuple(prior_windows_breached),
        now=now,
        skip=None,
    )


def _failed(check: PlatformAlertCheckInput, error: Exception, *, now: datetime, muted: bool) -> AlertCheckOutcome:
    """A check that could not reach a verdict, as the shared machine's error path sees it.

    The machine raises `consecutive_failures` and escalates to BROKEN, so an alert that fails
    every check stops being evaluated instead of failing forever. A transient error is classified
    as one so the policy can hold the counter.
    """
    classified = classify_alert_error(error)
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
    error_message: str | None = None,
) -> Decision:
    """A control-plane transition the check machine cannot express. The outcome advances the schedule."""
    recorded = _recorded(
        check,
        evaluation_key=_evaluation_key(now),
        # The notification is NONE here only because the check machine never ran.
        kind=AlertEventKind.BROKEN,
        new_state=outcome.new_state.value,
        notified=False,
        consecutive_failures=outcome.consecutive_failures,
        error_message=error_message,
    )
    _record_check_metrics(
        check, new_state=outcome.new_state.value, notification=NotificationAction.NONE, skip=skip, now=now
    )
    return recorded, None


def _evaluate_cohort(
    team: Team,
    checks: Sequence[PlatformAlertCheckInput],
    key: tuple,
    *,
    now: datetime,
    query_seconds: int,
    muted_ids: frozenset[UUID],
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
        return [
            _delivery(check, _failed(check, error, now=now, muted=check.id in muted_ids), window_end=date_to)
            for check in checks
        ]

    # One query serves the cohort, so every check in it records the same duration.
    query_duration_ms = int((time.monotonic() - query_started_at) * 1000)

    decided: list[Decision] = []
    for check in checks:
        muted = check.id in muted_ids
        buckets = result.per_alert.get(str(check.id), [])
        # ClickHouse emits no bucket for an empty window, so no buckets is a measured zero.
        value: float | None = float(buckets[-1].count) if buckets else 0.0
        duration_ms: int | None = query_duration_ms
        try:
            outcome = _evaluate_one(check, buckets, now=now, muted=muted)
        except Exception as error:
            logger.exception("Failed to evaluate a logs alert", check_id=str(check.id), error=str(error))
            outcome = _failed(check, error, now=now, muted=muted)
            # A check that reached no verdict measured nothing.
            value, duration_ms = None, None
        # Outside the block above on purpose. Resolving a destination reads the database, and a
        # failure there is not this check's failure.
        decided.append(_delivery(check, outcome, window_end=date_to, value=value, query_duration_ms=duration_ms))
    return decided


def _triage(
    checks: Sequence[PlatformAlertCheckInput], *, now: datetime, tz_name: str
) -> tuple[list[Decision], list[PlatformAlertCheckInput], frozenset[UUID]]:
    """Splits a batch into the checks a query can answer, the ones already decided, and the muted.

    A skip is a decision, not an omission. Dropping one records nothing, so its due time stays
    where it was and discovery hands the same check back on the next tick, forever.

    A schedule restriction decides nothing here. It mutes an announcement, so the check goes to the
    query like any other and its id lands in the muted set.
    """
    decided: list[Decision] = []
    evaluable: list[PlatformAlertCheckInput] = []
    muted_ids: set[UUID] = set()
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
                    skip=SkipReason.BROKEN_CONFIG,
                    now=now,
                    error_message=broken_reason,
                )
            )
            continue
        if _is_in_quiet_hours(check, now, tz_name):
            muted_ids.add(check.id)
        evaluable.append(check)
    return decided, evaluable, frozenset(muted_ids)


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

    decided, evaluable, muted_ids = _triage(checks, now=cutoff, tz_name=team.timezone)
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
        decided.extend(
            _evaluate_cohort(team, chunk, cohort_key, now=cutoff, query_seconds=query_seconds, muted_ids=muted_ids)
        )

    if unqueried:
        logger.warning(
            "Left logs alert cohorts unqueried on the batch query budget",
            team_id=team_id,
            slot=slot,
            unqueried=unqueried,
            budget_seconds=BATCH_QUERY_BUDGET_SECONDS,
        )
    return _collect(decided, team_id, slot, started_at)
