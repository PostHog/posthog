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

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from itertools import batched
from typing import Any, Final, cast
from uuid import UUID, uuid4

from django.conf import settings

import structlog

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.dataclasses import frozen
from posthog.exceptions import ClickHouseEstimatedQueryExecutionTimeTooLong, ClickHouseQueryTimeOut
from posthog.models import Team
from posthog.temporal.alerts.admission import hold_evaluation_slot, release_evaluation_slot

from products.alerts.backend.facade.destinations import configured_destination_template_ids
from products.alerts_platform.backend.facade.api import due_check_ids, due_checks, refresh_settings, slot_of
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertEventKind,
    GroupingMode,
    InstanceCheckState,
    MuteReason,
    PlatformAlertCheckInput,
    PlatformAlertOutcome,
    SkipReason,
    SourceBatchEvaluation,
    SourceKind,
)
from products.alerts_platform.backend.facade.grouping import (
    GroupObservation,
    bounded_grouping_key,
    decide_groups,
    delivery_parts,
    is_hashed_grouping_key,
    muted_value,
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
    decide_incident_action,
    evaluate_alert_check,
)
from products.alerts_platform.backend.facade.payload import MAX_BATCH_PAYLOAD_BYTES, payload_bytes
from products.alerts_platform.backend.facade.platform_metrics import (
    increment_checks,
    increment_checks_deferred,
    increment_checks_skipped,
    increment_deliveries_deferred,
    increment_notifications_muted,
    increment_state_transition,
    record_batch_duration,
    record_scheduler_lag,
    safe_record,
)
from products.alerts_platform.backend.facade.scheduling import is_utc_datetime_blocked, parse_blocked_windows_tuples
from products.logs.backend.alert_check_query import (
    BatchedAlertCheckQuery,
    BucketedCount,
    GroupedAlertCheckQuery,
    fetch_live_logs_checkpoint,
    is_projection_eligible,
    resolve_alert_date_to,
)
from products.logs.backend.alert_destinations import EVENT_KIND_CONFIG, EventKind
from products.logs.backend.alert_error_classifier import classify as classify_alert_error
from products.logs.backend.alert_evaluation_key import WINDOW_MARKER
from products.logs.backend.alert_group_columns import grouping_problem
from products.logs.backend.alert_lookback import rolling_check_lookback_minutes
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_alert_backfill import SETTINGS_FIELDS, platform_upsert_of
from products.logs.backend.platform_source_config import filters_of, logs_alert_url

# Private to the production activity. Reimplementing either would let this path drift from
# what the logs stack evaluates. Promoting them to a shared home is the deeper fix.
from products.logs.backend.temporal.activities import _derive_breaches, _detect_broken_filter_config
from products.logs.backend.temporal.batch_slot import LogsBatchAdmission, LogsBatchSlot
from products.logs.backend.temporal.constants import MAX_ALERT_COHORT_SIZE

logger = structlog.get_logger(__name__)

# A fleet-wide burst would otherwise return one activity payload over Temporal's ~2 MiB limit,
# which fails the whole batch rather than truncating it. The bound drops an outcome along with
# the preview it belongs to, so a breach this batch cannot announce keeps its due time.
MAX_DELIVERIES_PER_CYCLE = 500

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
# With the cohort budget this keeps every query of a batch inside `BATCH_SLOT_LEASE_SECONDS`, so a
# query never runs after its slot frees for another batch.
CHECKPOINT_QUERY_SECONDS = 10
# The errors ClickHouse raises when a query exceeds, or is estimated to exceed, its time limit.
_OUT_OF_TIME_ERRORS: Final = (ClickHouseQueryTimeOut, ClickHouseEstimatedQueryExecutionTimeTooLong)

INFLIGHT_KEY = "alerts:platform:logs:batches:inflight"
# A workflow takes the slot before its evaluation activity starts, and the activity holds it again
# under a fresh lease when it starts. So the lease has to outlast the rest of the take and the
# activity's queue time, and also the activity's run, with room to spare. Short enough that a worker
# that dies mid-batch frees its slot within two minutes.
BATCH_SLOT_LEASE_SECONDS = 90
_DEFERRED_COUNT_LIMIT = 10_000


@frozen
class LogsAlertCondition:
    """The logs bound, which the platform keeps under `source_config["condition"]`."""

    threshold_count: int
    threshold_operator: str
    window_minutes: int

    def __post_init__(self) -> None:
        # `_derive_breaches` reads any operator but `above` as `below`, so an unknown one would
        # decide the alert against the wrong side of its bound instead of failing.
        if self.threshold_operator not in LogsAlertConfiguration.ThresholdOperator.values:
            raise ValueError(f"Unknown threshold operator {self.threshold_operator!r}")
        # A threshold of 0 is valid: with `above` it fires on any matching log, as the logs API documents.
        for name, minimum in (("threshold_count", 0), ("window_minutes", 1)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer of at least {minimum}, got {value!r}")

    @classmethod
    def of(cls, check: PlatformAlertCheckInput) -> "LogsAlertCondition":
        return cls.from_condition(check.condition)

    @classmethod
    def from_condition(cls, condition: Mapping[str, Any]) -> "LogsAlertCondition":
        return cls(
            threshold_count=condition["threshold_count"],
            threshold_operator=condition["threshold_operator"],
            window_minutes=condition["window_minutes"],
        )

    def breached(self, count: float) -> bool:
        if self.threshold_operator == LogsAlertConfiguration.ThresholdOperator.ABOVE:
            return count > self.threshold_count
        return count < self.threshold_count


@frozen
class _QuerySubject:
    """A check as the logs query layer reads it, with the filters out of `source_config`."""

    id: UUID
    team_id: int
    filters: dict[str, Any]

    @classmethod
    def of(cls, check: PlatformAlertCheckInput) -> "_QuerySubject":
        return cls(id=check.id, team_id=check.team_id, filters=filters_of(check.source_config))


# The snooze lives on the alert row rather than the copy, and no history row states it.
_LIVE_FIELDS: Final = (*SETTINGS_FIELDS, "snooze_until")


def _broken_condition(check: PlatformAlertCheckInput) -> str | None:
    """A bound the cohort query cannot read. Caught here, because the cohort key reads it for
    every check in the batch, so one malformed row would otherwise stop the whole batch."""
    try:
        LogsAlertCondition.of(check)
    except ValueError as error:
        return f"The alert's threshold is invalid: {error}"
    return None


def _evaluation_key(check: PlatformAlertCheckInput, window_end: datetime) -> str:
    """Names the scheduled check, and the window it answered for.

    The slot is in the key because `resolve_alert_date_to` clamps the window end to the ingestion
    checkpoint. Two consecutive scheduled checks reach the same window end whenever the checkpoint
    has not moved, and a key built from the window alone would make them one evaluation to any
    reader deduplicating on it.

    Scoped to the alert by the row's own columns rather than by the string, so the key keeps one
    shape across sources. Both parts are read before anything is written, so a retry recomputes
    the same key.
    """
    return f"slot:{slot_of(check.next_check_at, window_end)}|{WINDOW_MARKER}{window_end.isoformat()}"


@frozen
class _QueryShape:
    """The part of `_cohort_key` a configuration fixes. Checks that differ here never share a query."""

    window_minutes: object
    evaluation_periods: int
    projection_eligible: bool

    @classmethod
    def of(cls, check: PlatformAlertCheckInput) -> "_QueryShape":
        return cls(
            window_minutes=check.condition.get("window_minutes"),
            evaluation_periods=check.evaluation_periods,
            projection_eligible=is_projection_eligible(filters_of(check.source_config)),
        )


def _schedule_group(check: PlatformAlertCheckInput) -> str:
    # The platform puts a team's checks with one group in one slot and spreads different groups
    # across slots, so one batch rarely holds more cohorts than `MAX_COHORTS_PER_CYCLE`.
    shape = _QueryShape.of(check)
    return f"{shape.window_minutes}:{shape.evaluation_periods}:{shape.projection_eligible}"


def _cohort_key(check: PlatformAlertCheckInput, checkpoint: datetime | None, now: datetime) -> tuple:
    shape = _QueryShape.of(check)
    return (
        shape.window_minutes,
        shape.evaluation_periods,
        check.check_interval_minutes,
        shape.projection_eligible,
        resolve_alert_date_to(check.next_check_at or now, checkpoint),
    )


def is_in_quiet_hours(schedule_restriction: dict | None, now: datetime, tz_name: str, *, alert_id: UUID) -> bool:
    """True when the alert's schedule restriction mutes an announcement at `now`.

    The check still runs, so an incident wholly inside the window is still recorded.
    """
    if not schedule_restriction:
        return False
    try:
        return is_utc_datetime_blocked(now, tz_name, parse_blocked_windows_tuples(schedule_restriction))
    except Exception as error:
        # A restriction we cannot parse must not decide the alert either way, so the check
        # proceeds and the production stack keeps ownership of the broken configuration.
        logger.exception(
            "Unparseable schedule restriction; evaluating anyway", alert_id=str(alert_id), error=str(error)
        )
        return False


def _snapshot(
    check: PlatformAlertCheckInput, prior_breached: tuple[bool, ...], instance: InstanceCheckState | None = None
) -> AlertSnapshot:
    instance = instance or check.instance()
    return AlertSnapshot(
        state=AlertState(instance.state),
        cooldown=timedelta(minutes=check.cooldown_minutes),
        last_notified_at=instance.last_notified_at,
        snooze_until=instance.snooze_until,
        consecutive_failures=check.consecutive_failures,
        evaluation_periods=check.evaluation_periods,
        datapoints_to_alarm=check.datapoints_to_alarm,
        recent_events_breached=prior_breached,
        firing_started_at=instance.firing_started_at,
    )


Decision = tuple[PlatformAlertOutcome, AlertDeliveryRequest | None]


@frozen
class _Triage:
    """What a batch splits into before any query runs."""

    decided: list[Decision]
    evaluable: list[PlatformAlertCheckInput]
    muted_ids: frozenset[UUID]


def _record_check_metrics(
    check: PlatformAlertCheckInput,
    *,
    new_state: str,
    notification: NotificationAction,
    muted_notification: NotificationAction = NotificationAction.NONE,
    skip: SkipReason | None = None,
    muted_by_quiet_hours: bool = False,
    now: datetime,
    grouping_key: str = "",
    record_lag: bool = True,
) -> None:
    safe_record(increment_checks, SourceKind.LOGS.value, notification.value)
    if skip is not None:
        safe_record(increment_checks_skipped, SourceKind.LOGS.value, skip.value)
    if muted_notification != NotificationAction.NONE:
        # The machine owns the snooze predicate, so the source's flag is what separates the two.
        mute_reason = MuteReason.QUIET_HOURS if muted_by_quiet_hours else MuteReason.SNOOZE
        safe_record(increment_notifications_muted, SourceKind.LOGS.value, mute_reason.value)
    previous_state = check.instance(grouping_key).state
    if previous_state != new_state:
        safe_record(increment_state_transition, SourceKind.LOGS.value, previous_state, new_state)
    if record_lag and check.next_check_at is not None:
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
    outcome: Outcome,
    evaluation_key: str,
    kind: AlertEventKind,
    notified: bool,
    now: datetime,
    value: float | None = None,
    error_message: str | None = None,
    query_duration_ms: int | None = None,
    muted_notification: str = "",
    disable: bool = False,
    failed: bool = False,
) -> PlatformAlertOutcome:
    """The one place a recorded outcome is built, so every path states the firing the same way."""
    return PlatformAlertOutcome.ungrouped(
        configuration_id=check.id,
        evaluation_key=evaluation_key,
        consecutive_failures=outcome.consecutive_failures,
        kind=kind,
        new_state=outcome.new_state.value,
        notified=notified,
        failed=failed,
        firing_episode=decide_firing_episode(_snapshot(check, ()), outcome, now, policy=PLATFORM_LOGS_ALERT_POLICY),
        value=value,
        muted_notification=muted_notification,
        error_message=error_message,
        query_duration_ms=query_duration_ms,
        disable=disable,
        # A broken alert is never discovered again, so its slot does not matter.
        schedule_group=None if outcome.new_state == AlertState.BROKEN else _schedule_group(check),
    )


def _delivery(
    check: PlatformAlertCheckInput,
    outcome: AlertCheckOutcome,
    *,
    window_end: datetime,
    now: datetime,
    value: float | None = None,
    query_duration_ms: int | None = None,
    failed: bool = False,
) -> Decision:
    """What the platform records for a verdict, and what delivery would announce for it."""
    recorded = _recorded(
        check,
        outcome=outcome,
        evaluation_key=_evaluation_key(check, window_end),
        kind=NOTIFICATION_EVENT_KINDS[outcome.notification],
        notified=outcome.update_last_notified_at,
        now=now,
        value=value,
        error_message=outcome.error_message,
        query_duration_ms=query_duration_ms,
        muted_notification=muted_value(outcome),
        disable=outcome.disable,
        failed=failed,
    )
    return recorded, _request(
        check, recorded, _ungrouped_move(check, outcome), sends_messages=outcome.notification != NotificationAction.NONE
    )


@frozen
class _Move:
    """The state a group left and the state it reached in one check."""

    before: AlertState
    after: AlertState


def _request(
    check: PlatformAlertCheckInput,
    recorded: PlatformAlertOutcome,
    moves: Mapping[str, _Move],
    *,
    sends_messages: bool,
) -> AlertDeliveryRequest | None:
    """The delivery for a recorded outcome, or None when it neither announces nor moves a firing.

    `moves` maps each group's key to the state it left and the state it reached. A firing that opens
    or closes needs a delivery even when cooldown or mute held the announcement, because a paging
    destination needs one resolve for every trigger. An alert with no such destination gets no
    incident action, so its edges start no delivery.
    """
    destination_alert_id = str(check.legacy_configuration_id)
    actions = {
        key: action
        for key, move in moves.items()
        if (action := decide_incident_action(move.before, move.after, policy=PLATFORM_LOGS_ALERT_POLICY)) is not None
    }
    if actions and not _has_incident_destination(check.team_id, destination_alert_id):
        actions = {}
    if not sends_messages and not actions:
        return None
    return AlertDeliveryRequest(
        source=SourceKind.LOGS,
        team_id=check.team_id,
        configuration_id=str(check.id),
        # The recorded key unchanged, so a delivery can address the row the check wrote. The
        # workflow id that has to be unique across alerts joins this to the configuration itself.
        evaluation_key=recorded.evaluation_key,
        destination_alert_id=destination_alert_id,
        event_ids_by_kind=_EVENT_IDS_BY_KIND,
        event_ids_by_incident_action=EVENT_IDS_BY_INCIDENT_ACTION,
        incident_actions=actions,
        sends_messages=sends_messages,
        # The logs alert page, as the HogFunction messages linked. An alert with no logs row has none.
        source_alert_url=logs_alert_url(check.team_id, check.legacy_configuration_id)
        if check.legacy_configuration_id is not None
        else None,
        owned_by_platform=check.owned_by_platform,
        overflowed=recorded.overflowed,
        overflow_is_lower_bound=recorded.overflow_is_lower_bound,
        parts=delivery_parts(recorded, actions),
    )


def _ungrouped_move(check: PlatformAlertCheckInput, outcome: Outcome) -> dict[str, _Move]:
    return {"": _Move(before=AlertState(check.instance().state), after=outcome.new_state)}


def _has_incident_destination(team_id: int, destination_alert_id: str) -> bool:
    """Whether a destination of this alert follows the incident events. Read only on a firing edge."""
    return bool(
        configured_destination_template_ids(
            team_id=team_id,
            alert_id=destination_alert_id,
            allowed_event_ids=tuple(EVENT_IDS_BY_INCIDENT_ACTION.values()),
        )
    )


# Which event id each announced kind's destinations filter on. Resolved here because the
# platform imports no source and cannot read `EVENT_KIND_CONFIG`.
_EVENT_IDS_BY_KIND: Final[dict[str, str]] = {
    kind.value: EVENT_KIND_CONFIG[cast(EventKind, kind.value)].event_id
    for kind in AlertEventKind
    if kind.value in EVENT_KIND_CONFIG
}

# Which event id an incident manager destination filters on for each incident action.
EVENT_IDS_BY_INCIDENT_ACTION: Final[dict[str, str]] = {
    spec.incident_action.value: spec.event_id for spec in EVENT_KIND_CONFIG.values() if spec.incident_action
}


def _evaluate_one(
    check: PlatformAlertCheckInput, buckets: list[BucketedCount], *, now: datetime, muted: bool
) -> AlertCheckOutcome:
    condition = LogsAlertCondition.of(check)
    current_breached, *prior_windows_breached = _derive_breaches(
        buckets, condition.threshold_count, condition.threshold_operator, check.evaluation_periods
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
    error_message: str,
) -> Decision:
    """A control-plane transition the check machine cannot express. The outcome advances the schedule."""
    recorded = _recorded(
        check,
        outcome=outcome,
        evaluation_key=_evaluation_key(check, now),
        # The notification is NONE here only because the check machine never ran.
        kind=AlertEventKind.BROKEN,
        notified=False,
        now=now,
        error_message=error_message,
        failed=True,
    )
    _record_check_metrics(
        check, new_state=outcome.new_state.value, notification=NotificationAction.NONE, skip=skip, now=now
    )
    return recorded, _request(check, recorded, _ungrouped_move(check, outcome), sends_messages=False)


def _evaluate_cohort(
    team: Team,
    checks: Sequence[PlatformAlertCheckInput],
    key: tuple,
    *,
    now: datetime,
    query_seconds: int,
    cut_short: bool,
    muted_ids: frozenset[UUID],
) -> list[Decision] | None:
    """The cohort's decisions, or None when it ran out of time that earlier queries spent."""
    window_minutes, evaluation_periods, cadence_minutes, projection_eligible, date_to = key
    lookback = rolling_check_lookback_minutes(window_minutes, cadence_minutes, evaluation_periods)

    try:
        result = BatchedAlertCheckQuery(
            team=team,
            alerts=[_QuerySubject.of(check) for check in checks],
            date_from=date_to - timedelta(minutes=lookback),
            date_to=date_to,
            projection_eligible=projection_eligible,
            max_execution_time=query_seconds,
            ch_user=ClickHouseUser.ALERTS_PLATFORM_LOGS,
        ).execute_rolling_checks(date_to, window_minutes, cadence_minutes, evaluation_periods)
    except Exception as error:
        if cut_short and isinstance(error, _OUT_OF_TIME_ERRORS):
            return None
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
            _delivery(
                check,
                _failed(check, error, now=now, muted=check.id in muted_ids),
                window_end=date_to,
                now=now,
                failed=True,
            )
            for check in checks
        ]

    decided: list[Decision] = []
    for check in checks:
        muted = check.id in muted_ids
        buckets = result.per_alert.get(str(check.id), [])
        # ClickHouse emits no bucket for an empty window, so no buckets is a measured zero.
        value: float | None = float(buckets[-1].count) if buckets else 0.0
        # One query serves the cohort, so every check in it records the same duration.
        duration_ms: int | None = result.query_duration_ms
        failed = False
        try:
            outcome = _evaluate_one(check, buckets, now=now, muted=muted)
        except Exception as error:
            logger.exception("Failed to evaluate a logs alert", check_id=str(check.id), error=str(error))
            outcome = _failed(check, error, now=now, muted=muted)
            # A check that reached no verdict measured nothing.
            value, duration_ms, failed = None, None, True
        # Outside the block above on purpose. Resolving a destination reads the database, and a
        # failure there is not this check's failure.
        decided.append(
            _delivery(
                check,
                outcome,
                window_end=date_to,
                now=now,
                value=value,
                query_duration_ms=duration_ms,
                failed=failed,
            )
        )
    return decided


def _as_configured_now(
    checks: Sequence[PlatformAlertCheckInput], *, team_id: int, now: datetime
) -> tuple[list[PlatformAlertCheckInput], list[Decision]]:
    """Reads each check's logs alert, so the check evaluates what the logs stack evaluates.

    The copy is a seed, so an edit made in the logs product since the backfill lives only on the
    logs row. Evaluating the copy as stored would read that drift as disagreement. A drifted copy's
    settings are written back before it is evaluated, because history and messages read the stored
    copy, so a message would otherwise quote the old threshold. The write leaves the schedule alone,
    so a retried attempt finds the same checks due. A changed check interval still needs a backfill.

    A copy whose logs alert is gone or disabled stops: the logs stack runs no check for it, so it
    switches itself off, and the next backfill turns it back on if the alert is enabled again.

    A copy the platform owns is not a seed: every edit reaches it directly, from the logs API or the
    platform's, so it is evaluated as stored. It still needs its logs row on the copy's team. A row in
    a child environment has its logs there, and the query would read the project's instead.
    """
    legacy_ids = [check.legacy_configuration_id for check in checks]
    alerts = {alert.id: alert for alert in LogsAlertConfiguration.objects.filter(team_id=team_id, id__in=legacy_ids)}
    current: list[PlatformAlertCheckInput] = []
    stopped: list[Decision] = []
    for check in checks:
        alert = alerts.get(check.legacy_configuration_id)
        if check.owned_by_platform and alert is not None:
            current.append(check)
            continue
        if alert is None or not alert.enabled:
            stopped.append(_stopped(check, now=now))
            continue
        if not isinstance(alert.filters, dict):
            # The copy cannot be built, and raising would stop every other check in the batch.
            stopped.append(
                _held(
                    check,
                    apply_broken_config(_snapshot(check, ())),
                    skip=SkipReason.BROKEN_CONFIG,
                    now=now,
                    error_message="The alert's filters are not an object.",
                )
            )
            continue
        upsert = platform_upsert_of(alert)
        if any(getattr(check, field) != getattr(upsert, field) for field in SETTINGS_FIELDS):
            try:
                refresh_settings(team_id, check.id, upsert)
            except Exception:
                # History records the stored copy, so the check evaluates that copy and stays true to it.
                logger.exception("Failed to bring a platform logs copy up to date", check_id=str(check.id))
                current.append(check)
                continue
        # A logs mute lives on the configuration alone, so each instance takes the live one too.
        instances = tuple(replace(instance, snooze_until=upsert.snooze_until) for instance in check.instances)
        current.append(replace(check, instances=instances, **{field: getattr(upsert, field) for field in _LIVE_FIELDS}))
    return current, stopped


def _stopped(check: PlatformAlertCheckInput, *, now: datetime) -> Decision:
    """A check whose logs alert no longer runs. It leaves the state alone and disables the copy."""
    state = check.instance().state
    if check.grouping.mode == GroupingMode.SINGLE:
        unchanged = ControlPlaneOutcome(new_state=AlertState(state), consecutive_failures=check.consecutive_failures)
        recorded = _recorded(
            check,
            outcome=unchanged,
            evaluation_key=_evaluation_key(check, now),
            kind=AlertEventKind.CHECK,
            notified=False,
            now=now,
            disable=True,
        )
    else:
        # No group was checked, so each instance keeps its state and no row is created.
        recorded = PlatformAlertOutcome(
            configuration_id=check.id,
            evaluation_key=_evaluation_key(check, now),
            consecutive_failures=check.consecutive_failures,
            disable=True,
        )
    _record_check_metrics(
        check, new_state=state, notification=NotificationAction.NONE, skip=SkipReason.SOURCE_RULE, now=now
    )
    return recorded, None


def grouping_key_of(labels: dict[str, str]) -> str:
    """The instance key for one group's label values."""
    return bounded_grouping_key(json.dumps(labels, sort_keys=True, separators=(",", ":")))


def _labels_of(grouping_key: str) -> dict[str, str] | None:
    """The labels `grouping_key_of` encoded, or None for a hashed key, which keeps no labels."""
    if is_hashed_grouping_key(grouping_key):
        return None
    try:
        labels = json.loads(grouping_key)
    except ValueError:
        return None
    return labels if isinstance(labels, dict) else None


def _broken_grouping(check: PlatformAlertCheckInput) -> str | None:
    if check.grouping.mode == GroupingMode.SINGLE:
        return None
    return grouping_problem(check.grouping.keys, check.condition.get("threshold_operator"))


def _evaluate_grouped(
    team: Team,
    check: PlatformAlertCheckInput,
    *,
    checkpoint: datetime | None,
    now: datetime,
    query_seconds: int,
    cut_short: bool,
    muted: bool,
) -> Decision | None:
    """One grouped alert: its own query, then the platform's per-group decision.

    An open group the query did not return had no matching log, so it is checked against a zero
    count and can resolve.
    """
    condition = LogsAlertCondition.of(check)
    date_to = resolve_alert_date_to(check.next_check_at or now, checkpoint)
    lookback = rolling_check_lookback_minutes(
        condition.window_minutes, check.check_interval_minutes, check.evaluation_periods
    )
    open_keys = check.open_keys()
    try:
        result = GroupedAlertCheckQuery(
            team=team,
            alert=_QuerySubject.of(check),
            date_from=date_to - timedelta(minutes=lookback),
            date_to=date_to,
            group_by=check.grouping.keys,
            open_groups=[labels for key in open_keys if (labels := _labels_of(key)) is not None],
            worst_is_highest=condition.threshold_operator == LogsAlertConfiguration.ThresholdOperator.ABOVE,
            threshold_count=condition.threshold_count,
            datapoints_to_alarm=check.datapoints_to_alarm,
            # Room for every open group and a full cap of new ones, so admission sees the worst. The
            # query's one row past that reaches admission too, and when it breaches, admission finds
            # no room for it and reports the cut as overflow.
            limit=len(open_keys) + check.grouping.max_instances,
            max_execution_time=query_seconds,
            ch_user=ClickHouseUser.ALERTS_PLATFORM_LOGS,
        ).execute_rolling_checks(
            date_to, condition.window_minutes, check.check_interval_minutes, check.evaluation_periods
        )
    except Exception as error:
        if cut_short and isinstance(error, _OUT_OF_TIME_ERRORS):
            return None
        logger.exception("Grouped logs alert query failed", check_id=str(check.id), error=str(error))
        return _delivery(check, _failed(check, error, now=now, muted=muted), window_end=date_to, now=now, failed=True)

    counts = {grouping_key_of(group.labels): group for group in result.groups}

    def observe(key: str, buckets: list[BucketedCount], labels: dict[str, str]) -> GroupObservation:
        current_breached, *prior_breached = _derive_breaches(
            buckets, condition.threshold_count, condition.threshold_operator, check.evaluation_periods
        ) or (False,)
        return GroupObservation(
            grouping_key=key,
            current_breached=current_breached,
            prior_breached=tuple(prior_breached),
            value=float(buckets[-1].count) if buckets else 0.0,
            labels=labels,
        )

    def absent(key: str) -> GroupObservation | None:
        labels = _labels_of(key)
        # A hashed key keeps no labels, so the query cannot put that open group first, and the limit
        # can cut it while it still breaches. Its absence means no matching log only when nothing was cut.
        if result.truncated and labels is None:
            return None
        return observe(key, result.zero_counts(), labels or {})

    decision = decide_groups(
        check,
        [observe(key, group.counts, group.labels) for key, group in counts.items()],
        snapshot_of=lambda instance, prior: _snapshot(check, prior, instance),
        policy=PLATFORM_LOGS_ALERT_POLICY,
        now=now,
        muted=muted,
        absent=absent,
    )
    for index, verdict in enumerate(decision.verdicts):
        _record_check_metrics(
            check,
            new_state=verdict.group.new_state,
            notification=verdict.outcome.notification,
            muted_notification=verdict.outcome.muted_notification,
            muted_by_quiet_hours=muted,
            now=now,
            grouping_key=verdict.group.grouping_key,
            record_lag=index == 0,
        )
    recorded = decision.as_outcome(
        configuration_id=check.id,
        evaluation_key=_evaluation_key(check, date_to),
        grouping=check.grouping,
        query_duration_ms=result.query_duration_ms,
        results_cut=result.truncated,
    )
    return recorded, _request(
        check,
        recorded,
        {
            verdict.group.grouping_key: _Move(before=verdict.snapshot.state, after=verdict.outcome.new_state)
            for verdict in decision.verdicts
        },
        sends_messages=any(verdict.outcome.notification != NotificationAction.NONE for verdict in decision.verdicts),
    )


def _triage(checks: Sequence[PlatformAlertCheckInput], *, now: datetime, tz_name: str) -> _Triage:
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
        broken_reason = (
            _detect_broken_filter_config(filters_of(check.source_config))
            or _broken_condition(check)
            or _broken_grouping(check)
        )
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
        if is_in_quiet_hours(check.schedule_restriction, now, tz_name, alert_id=check.id):
            muted_ids.add(check.id)
        evaluable.append(check)
    return _Triage(decided=decided, evaluable=evaluable, muted_ids=frozenset(muted_ids))


def _collect(decided: Sequence[Decision], team_id: int, slot: str, started_at: float) -> SourceBatchEvaluation:
    """Applies the payload bounds and reports the batch.

    A check that does not fit is left out with its delivery, so it keeps its due time and a later
    tick evaluates it again. The byte budget counts every check, including one with no delivery,
    because a grouped check's outcome grows with its groups whether or not it announces.
    """
    outcomes: list[PlatformAlertOutcome] = []
    deliveries: list[AlertDeliveryRequest] = []
    deferred_deliveries = 0
    deferred_checks = 0
    spent = 0
    for outcome, delivery in decided:
        if delivery is not None and len(deliveries) >= MAX_DELIVERIES_PER_CYCLE:
            deferred_deliveries += 1
            continue
        size = payload_bytes(outcome) + (payload_bytes(delivery) if delivery is not None else 0)
        if spent + size > MAX_BATCH_PAYLOAD_BYTES:
            deferred_checks += 1
            continue
        spent += size
        outcomes.append(outcome)
        if delivery is not None:
            deliveries.append(delivery)

    if deferred_deliveries:
        logger.warning(
            "Deferred logs alert deliveries over the batch payload bound",
            team_id=team_id,
            slot=slot,
            delivered=len(deliveries),
            deferred=deferred_deliveries,
        )
        safe_record(increment_deliveries_deferred, SourceKind.LOGS.value, deferred_deliveries)
    if deferred_checks:
        logger.warning(
            "Deferred logs alert checks over the batch payload byte budget",
            team_id=team_id,
            slot=slot,
            recorded=len(outcomes),
            deferred=deferred_checks,
            budget_bytes=MAX_BATCH_PAYLOAD_BYTES,
        )
        safe_record(increment_checks_deferred, SourceKind.LOGS.value, deferred_checks)
    safe_record(record_batch_duration, SourceKind.LOGS.value, int((time.monotonic() - started_at) * 1000))
    return SourceBatchEvaluation(
        outcomes=tuple(outcomes), deliveries=tuple(deliveries), omitted=deferred_deliveries + deferred_checks
    )


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
        return SourceBatchEvaluation(outcomes=(), deliveries=())

    # One slot per batch, because a batch runs its cohort queries one after another, so the batches
    # in flight bound the parallel run's concurrent queries across the fleet. A batch the pool turns
    # away records nothing, so its checks stay due and a later tick finds them again.
    # Unique per execution: a redispatch of a batch whose old query still runs must hold its own slot.
    member = f"{team_id}:{slot}:{uuid4().hex}"
    held_until = hold_evaluation_slot(
        member,
        limit=settings.ALERTS_PLATFORM_LOGS_MAX_INFLIGHT_BATCHES,
        lease_seconds=BATCH_SLOT_LEASE_SECONDS,
        key=INFLIGHT_KEY,
    )
    if held_until is None:
        logger.info("Deferred a platform logs batch over the pool limit", team_id=team_id, slot=slot)
        safe_record(increment_checks_deferred, SourceKind.LOGS.value, len(checks))
        return SourceBatchEvaluation(outcomes=(), deliveries=(), omitted=len(checks))
    try:
        return _evaluate_admitted(team_id, slot, cutoff, checks, started_at=started_at)
    finally:
        release_evaluation_slot(member, held_until=held_until, key=INFLIGHT_KEY)


def take_logs_batch_slot(
    team_id: int, slot: str, cutoff: datetime, *, member: str, first: bool, final: bool
) -> LogsBatchAdmission:
    """One try at a pool slot for a batch, without waiting. The workflow waits between tries.

    `member` comes from the workflow, so a retried attempt finds the slot an earlier attempt took
    instead of taking a second one. Only the first try asks whether the batch is due: nothing else
    evaluates this batch key while its workflow waits, and the evaluation reads the checks again.
    `final` marks the last try: a batch that still finds no room misses its tick, and only that try
    counts its checks as deferred.
    """
    due: tuple[str, ...] = ()
    if first or final:
        # The last try counts every due check it defers, so only it reads more than one id.
        due = due_check_ids(team_id, SourceKind.LOGS.value, slot, cutoff, limit=_DEFERRED_COUNT_LIMIT if final else 1)
        if not due:
            return LogsBatchAdmission(due=False)
    held_until = hold_evaluation_slot(
        member,
        limit=settings.ALERTS_PLATFORM_LOGS_MAX_INFLIGHT_BATCHES,
        lease_seconds=BATCH_SLOT_LEASE_SECONDS,
        key=INFLIGHT_KEY,
    )
    if held_until is None:
        if final:
            logger.info("Deferred a platform logs batch over the pool limit", team_id=team_id, slot=slot)
            safe_record(increment_checks_deferred, SourceKind.LOGS.value, len(due))
        return LogsBatchAdmission(due=True)
    return LogsBatchAdmission(due=True, slot=LogsBatchSlot(member=member, held_until=held_until))


def evaluate_held_logs_batch(team_id: int, slot: str, cutoff: datetime, held: LogsBatchSlot) -> SourceBatchEvaluation:
    """`evaluate_logs_batch` for a batch whose workflow already took its slot. Releases the slot."""
    started_at = time.monotonic()
    # Hold the slot again under a fresh lease. The take's lease can lapse while this activity waits in
    # the queue, and a timed-out take attempt can rewrite the expiry after its retry returned. A batch
    # whose slot lapsed while the pool filled finds no room here, and its checks stay due.
    held_until = hold_evaluation_slot(
        held.member,
        limit=settings.ALERTS_PLATFORM_LOGS_MAX_INFLIGHT_BATCHES,
        lease_seconds=BATCH_SLOT_LEASE_SECONDS,
        key=INFLIGHT_KEY,
    )
    if held_until is None:
        logger.info("Deferred a platform logs batch whose slot lapsed", team_id=team_id, slot=slot)
        return SourceBatchEvaluation(outcomes=(), deliveries=())
    try:
        checks = due_checks(team_id, SourceKind.LOGS.value, slot, cutoff)
        if not checks:
            return SourceBatchEvaluation(outcomes=(), deliveries=())
        return _evaluate_admitted(team_id, slot, cutoff, checks, started_at=started_at)
    finally:
        release_evaluation_slot(held.member, held_until=held_until, key=INFLIGHT_KEY)


def release_logs_batch_slot(held: LogsBatchSlot) -> None:
    """Frees a slot whose evaluation never started. A no-op once that evaluation held the slot again."""
    release_evaluation_slot(held.member, held_until=held.held_until, key=INFLIGHT_KEY)


def _evaluate_admitted(
    team_id: int, slot: str, cutoff: datetime, checks: Sequence[PlatformAlertCheckInput], *, started_at: float
) -> SourceBatchEvaluation:
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return SourceBatchEvaluation(outcomes=(), deliveries=())

    current, stopped = _as_configured_now(checks, team_id=team_id, now=cutoff)
    triage = _triage(current, now=cutoff, tz_name=team.timezone)
    if not triage.evaluable:
        # Returns before the checkpoint query below, which nothing left would use.
        return _collect([*stopped, *triage.decided], team_id, slot, started_at)
    decided = [*stopped, *triage.decided]

    # One checkpoint for the pass, matching the production discovery activity. A failure falls
    # back to wall-clock rather than ending the batch.
    try:
        checkpoint = fetch_live_logs_checkpoint(
            team, ch_user=ClickHouseUser.ALERTS_PLATFORM_LOGS, max_execution_time=CHECKPOINT_QUERY_SECONDS
        )
    except Exception as error:
        logger.exception("Failed to fetch logs ingestion checkpoint; falling back to wall-clock", error=str(error))
        checkpoint = None

    cohorts: dict[tuple, list[PlatformAlertCheckInput]] = {}
    grouped: list[PlatformAlertCheckInput] = []
    for check in triage.evaluable:
        if check.grouping.mode != GroupingMode.SINGLE:
            grouped.append(check)
            continue
        cohorts.setdefault(_cohort_key(check, checkpoint, cutoff), []).append(check)

    if len(cohorts) > MAX_COHORTS_PER_CYCLE:
        logger.warning(
            "Truncating logs alert cohorts to keep the batch inside its activity timeout",
            produced=len(cohorts),
            evaluated=MAX_COHORTS_PER_CYCLE,
        )

    deadline = started_at + BATCH_QUERY_BUDGET_SECONDS
    unqueried = 0
    # A query that runs out of time the queries before it spent records nothing, so its checks keep
    # their due time. Discovery then hands their slot back alone, and the first query of that batch
    # has the full time, so a query too slow even with it counts toward BROKEN rather than retrying
    # forever. The first query of a batch has nothing before it to blame, so its timeout counts.
    queried = False
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
        cohort_decided = _evaluate_cohort(
            team,
            chunk,
            cohort_key,
            now=cutoff,
            query_seconds=query_seconds,
            cut_short=queried and query_seconds < MAX_QUERY_SECONDS,
            muted_ids=triage.muted_ids,
        )
        queried = True
        if cohort_decided is None:
            unqueried += len(chunk)
            continue
        decided.extend(cohort_decided)
    for check in grouped:
        query_seconds = min(MAX_QUERY_SECONDS, int(deadline - time.monotonic()))
        if query_seconds < MIN_QUERY_SECONDS:
            unqueried += 1
            continue
        grouped_decided = _evaluate_grouped(
            team,
            check,
            checkpoint=checkpoint,
            now=cutoff,
            query_seconds=query_seconds,
            cut_short=queried and query_seconds < MAX_QUERY_SECONDS,
            muted=check.id in triage.muted_ids,
        )
        queried = True
        if grouped_decided is None:
            unqueried += 1
            continue
        decided.append(grouped_decided)

    if unqueried:
        logger.warning(
            "Left logs alert cohorts unqueried on the batch query budget",
            team_id=team_id,
            slot=slot,
            unqueried=unqueried,
            budget_seconds=BATCH_QUERY_BUDGET_SECONDS,
        )
    return _collect(decided, team_id, slot, started_at)
