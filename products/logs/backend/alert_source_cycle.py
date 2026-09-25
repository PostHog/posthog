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
    GroupTransition,
    PlatformAlertCheck,
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
    NotificationAction,
    evaluate_alert_check,
)
from products.alerts.backend.facade.platform_alerts import due_checks
from products.alerts.backend.facade.platform_metrics import (
    increment_checks,
    increment_deliveries_deferred,
    increment_state_transition,
    record_batch_duration,
    record_scheduler_lag,
    safe_record,
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
from products.logs.backend.alert_utils import next_allowed_check_at

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


def _cohort_key(check: PlatformAlertCheck, checkpoint: datetime | None, now: datetime) -> tuple:
    return (
        check.window_minutes,
        check.evaluation_periods,
        check.check_interval_minutes,
        is_projection_eligible(check.source_config),
        resolve_alert_date_to(check.next_check_at or now, checkpoint),
    )


def _is_in_quiet_hours(check: PlatformAlertCheck, team: Team, now: datetime) -> bool:
    """True when the alert's schedule restriction blocks a check at `now`."""
    if not check.schedule_restriction:
        return False
    try:
        return (
            next_allowed_check_at(now, team_timezone=team.timezone, schedule_restriction=check.schedule_restriction)
            > now
        )
    except Exception as error:
        # A restriction we cannot parse must not decide the alert either way, so the check
        # proceeds and the production stack keeps ownership of the broken configuration.
        logger.exception(
            "Unparseable schedule restriction; evaluating anyway", check_id=str(check.id), error=str(error)
        )
        return False


def _snapshot(check: PlatformAlertCheck, prior_breached: tuple[bool, ...]) -> AlertSnapshot:
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


def _evaluate_one(
    check: PlatformAlertCheck, buckets: list[BucketedCount], *, window_end: datetime, now: datetime
) -> tuple[PlatformAlertOutcome, AlertDeliveryPreview | None]:
    current_breached, *prior_windows_breached = _derive_breaches(
        buckets, check.threshold_count, check.threshold_operator, check.evaluation_periods
    ) or (False,)

    # `LOGS_ALERT_POLICY` is how the shared machine expresses this source's semantics, so the
    # decision is the one the logs stack reaches without routing through the logs product.
    outcome = evaluate_alert_check(
        _snapshot(check, tuple(prior_windows_breached)),
        CheckInput(threshold_breached=current_breached),
        now,
        policy=LOGS_ALERT_POLICY,
    )
    recorded = PlatformAlertOutcome(
        configuration_id=check.id,
        new_state=outcome.new_state.value,
        notified=outcome.update_last_notified_at,
        consecutive_failures=outcome.consecutive_failures,
        disable=outcome.disable,
    )
    safe_record(increment_checks, SourceKind.LOGS.value, outcome.notification.value)
    if check.state != outcome.new_state.value:
        safe_record(increment_state_transition, SourceKind.LOGS.value, check.state, outcome.new_state.value)
    if check.next_check_at is not None:
        lag_ms = int((now - check.next_check_at).total_seconds() * 1000)
        if lag_ms > 0:
            safe_record(record_scheduler_lag, SourceKind.LOGS.value, lag_ms)
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


def _evaluate_cohort(
    team: Team, checks: Sequence[PlatformAlertCheck], key: tuple, *, now: datetime, query_seconds: int
) -> list[tuple[PlatformAlertOutcome, AlertDeliveryPreview | None]]:
    window_minutes, evaluation_periods, cadence_minutes, projection_eligible, date_to = key
    lookback = rolling_check_lookback_minutes(window_minutes, cadence_minutes, evaluation_periods)

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
            "Logs alert cohort query failed; skipping the cohort",
            team_id=team.id,
            cohort_size=len(checks),
            error=str(error),
        )
        return []

    decided: list[tuple[PlatformAlertOutcome, AlertDeliveryPreview | None]] = []
    for check in checks:
        try:
            decided.append(_evaluate_one(check, result.per_alert.get(str(check.id), []), window_end=date_to, now=now))
        except Exception as error:
            logger.exception("Failed to evaluate a logs alert; skipping it", check_id=str(check.id), error=str(error))
    return decided


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
    # Production excludes a structurally broken filter before evaluating, so including one
    # would record a transition production would never record.
    checks = tuple(c for c in checks if _detect_broken_filter_config(c.source_config) is None)
    if not checks:
        return SourceBatchEvaluation(outcomes=(), previews=())

    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return SourceBatchEvaluation(outcomes=(), previews=())
    checks = tuple(c for c in checks if not _is_in_quiet_hours(c, team, cutoff))
    if not checks:
        return SourceBatchEvaluation(outcomes=(), previews=())

    # One checkpoint for the pass, matching the production discovery activity. A failure falls
    # back to wall-clock rather than ending the batch.
    try:
        checkpoint = fetch_live_logs_checkpoint(team)
    except Exception as error:
        logger.exception("Failed to fetch logs ingestion checkpoint; falling back to wall-clock", error=str(error))
        checkpoint = None

    cohorts: dict[tuple, list[PlatformAlertCheck]] = {}
    for check in checks:
        cohorts.setdefault(_cohort_key(check, checkpoint, cutoff), []).append(check)

    if len(cohorts) > MAX_COHORTS_PER_CYCLE:
        logger.warning(
            "Truncating logs alert cohorts to keep the batch inside its activity timeout",
            produced=len(cohorts),
            evaluated=MAX_COHORTS_PER_CYCLE,
        )

    outcomes: list[PlatformAlertOutcome] = []
    previews: list[AlertDeliveryPreview] = []
    omitted = 0
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
            unqueried += len(chunk)
            continue
        for outcome, preview in _evaluate_cohort(team, chunk, cohort_key, now=cutoff, query_seconds=query_seconds):
            if preview is not None and len(previews) >= MAX_PREVIEWS_PER_CYCLE:
                omitted += 1
                continue
            outcomes.append(outcome)
            if preview is not None:
                previews.append(preview)

    if unqueried:
        logger.warning(
            "Left logs alert cohorts unqueried on the batch query budget",
            team_id=team_id,
            slot=slot,
            unqueried=unqueried,
            budget_seconds=BATCH_QUERY_BUDGET_SECONDS,
        )
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
