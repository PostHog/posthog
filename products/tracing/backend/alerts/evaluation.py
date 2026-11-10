"""Evaluation of due traces alerts on the shared alerts platform.

Each check runs one query over `trace_spans` that measures every rolling window of its N-of-M
lookback, ending at the check's due time held back to the ingestion checkpoint. Under grouping,
each service or operation is a group.

A window with no request measures zero for a count, and no data for an error rate or a latency.
No data never breaches. An open group the query did not return had no request in the lookback, so
it is judged as such and can resolve, unless the query cut the result short and the group's
key is hashed, so the query could not put it first.

This reads and decides. It writes nothing, so a retried attempt reads the same due checks and makes
the same decisions. The platform records the outcomes in its own activity.
"""

import json
import time
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Final
from uuid import uuid4

from django.conf import settings

import structlog
from pydantic import ValidationError

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.exceptions import ClickHouseEstimatedQueryExecutionTimeTooLong, ClickHouseQueryTimeOut
from posthog.models import Team
from posthog.temporal.alerts.admission import hold_evaluation_slot, release_evaluation_slot

from products.alerts_platform.backend.facade.api import due_checks, has_incident_destination, slot_of
from products.alerts_platform.backend.facade.check_errors import classify_check_error
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    InstanceCheckState,
    PlatformAlertCheckInput,
    PlatformAlertOutcome,
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
    PLATFORM_DEFAULT_ALERT_POLICY,
    AlertSnapshot,
    AlertState,
    CheckInput,
    NotificationAction,
    decide_firing_episode,
    decide_incident_action,
    evaluate_alert_check,
)
from products.alerts_platform.backend.facade.payload import MAX_BATCH_PAYLOAD_BYTES, payload_bytes
from products.alerts_platform.backend.facade.platform_metrics import (
    increment_checks,
    increment_checks_deferred,
    increment_state_transition,
    record_batch_duration,
    safe_record,
)
from products.alerts_platform.backend.facade.rolling_checks import (
    derive_breaches,
    resolve_check_end,
    rolling_check_ranges,
)
from products.alerts_platform.backend.facade.scheduling import is_utc_datetime_blocked, parse_blocked_windows_tuples
from products.tracing.backend.alerts.check_query import GroupValues, run_check_query, window_values_with_no_requests
from products.tracing.backend.alerts.destinations import EVENT_IDS_BY_INCIDENT_ACTION, EVENT_IDS_BY_KIND
from products.tracing.backend.alerts.freshness import fetch_traces_checkpoint
from products.tracing.backend.alerts.source_config import TracesPlatformAlertCondition, TracesPlatformAlertConfig
from products.tracing.backend.alerts.wording import alert_url

logger = structlog.get_logger(__name__)

SOURCE: Final = SourceKind.TRACES
POLICY: Final = PLATFORM_DEFAULT_ALERT_POLICY

# The batch's query time, which `EVALUATE_START_TO_CLOSE` in the workflow sits above. Checks run one
# after another, and a check the budget has no room for keeps its due time for a later tick.
BATCH_QUERY_BUDGET_SECONDS: Final = 25
# No single query may spend the whole budget, or the first slow one starves the rest.
MAX_QUERY_SECONDS: Final = 20
# Below this there is no point starting another query.
MIN_QUERY_SECONDS: Final = 2
CHECKPOINT_QUERY_SECONDS: Final = 5
_OUT_OF_TIME_ERRORS: Final = (ClickHouseQueryTimeOut, ClickHouseEstimatedQueryExecutionTimeTooLong)
INFLIGHT_KEY: Final = "alerts:platform:traces:batches:inflight"
# Outlasts the evaluation activity's run, so a slot frees before its batch ends only when a worker
# died mid-batch.
BATCH_SLOT_LEASE_SECONDS: Final = 90

_INVALID_CONFIG: Final = "The alert's configuration is no longer valid. Edit the alert to fix it."

Decision = tuple[PlatformAlertOutcome, AlertDeliveryRequest | None]


def evaluate_traces_alert_batch(team_id: int, slot: str, cutoff: datetime) -> SourceBatchEvaluation:
    """Evaluates one batch key of traces alerts against the tick's cutoff."""
    started_at = time.monotonic()
    checks = due_checks(team_id, SOURCE.value, slot, cutoff)
    if not checks:
        return SourceBatchEvaluation(outcomes=(), deliveries=())
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return SourceBatchEvaluation(outcomes=(), deliveries=())

    # One slot per batch, because a batch runs its queries one after another, so the batches in
    # flight bound the concurrent traces queries across the fleet. A batch the pool turns away
    # records nothing, so its checks stay due and a later tick finds them again.
    # Unique per execution: a redispatch of a batch whose old query still runs must hold its own slot.
    member = f"{team_id}:{slot}:{uuid4().hex}"
    held_until = hold_evaluation_slot(
        member,
        limit=settings.ALERTS_PLATFORM_TRACES_MAX_INFLIGHT_BATCHES,
        lease_seconds=BATCH_SLOT_LEASE_SECONDS,
        key=INFLIGHT_KEY,
    )
    if held_until is None:
        logger.info("Deferred a platform traces batch over the pool limit", team_id=team_id, slot=slot)
        safe_record(increment_checks_deferred, SOURCE.value, len(checks))
        return SourceBatchEvaluation(outcomes=(), deliveries=(), omitted=len(checks))
    try:
        return _evaluate_admitted(team, slot, checks, cutoff=cutoff, started_at=started_at)
    finally:
        release_evaluation_slot(member, held_until=held_until, key=INFLIGHT_KEY)


def _evaluate_admitted(
    team: Team, slot: str, checks: Sequence[PlatformAlertCheckInput], *, cutoff: datetime, started_at: float
) -> SourceBatchEvaluation:
    checkpoint = _checkpoint(team)
    deadline = started_at + BATCH_QUERY_BUDGET_SECONDS
    decided: list[Decision] = []
    # A query that runs out of the time the queries before it spent records nothing, so its check
    # keeps its due time and a later batch gives it the full time. A batch's first query has nothing
    # before it to blame, so its timeout counts toward BROKEN.
    queried = False
    for check in checks:
        query_seconds = int(min(MAX_QUERY_SECONDS, deadline - time.monotonic()))
        if query_seconds < MIN_QUERY_SECONDS:
            break
        decision = _evaluate(
            team,
            check,
            check_end=resolve_check_end(check.next_check_at or cutoff, checkpoint),
            now=cutoff,
            query_seconds=query_seconds,
            cut_short=queried and query_seconds < MAX_QUERY_SECONDS,
            muted=_in_quiet_hours(check, cutoff, team.timezone),
        )
        queried = True
        if decision is not None:
            decided.append(decision)
    evaluation = _collect(decided, team_id=team.id, slot=slot, past_budget=len(checks) - len(decided))
    safe_record(record_batch_duration, SOURCE.value, int((time.monotonic() - started_at) * 1000))
    return evaluation


def _checkpoint(team: Team) -> datetime | None:
    try:
        return fetch_traces_checkpoint(
            team, ch_user=ClickHouseUser.ALERTS_PLATFORM_TRACES, max_execution_time=CHECKPOINT_QUERY_SECONDS
        )
    except Exception:
        # Without a checkpoint the batch still runs, at its due time.
        logger.exception("Failed to fetch the traces ingestion checkpoint", team_id=team.id)
        return None


def _in_quiet_hours(check: PlatformAlertCheckInput, now: datetime, tz_name: str) -> bool:
    try:
        return is_utc_datetime_blocked(now, tz_name, parse_blocked_windows_tuples(check.schedule_restriction))
    except Exception:
        # A restriction that cannot be read must not hold back a breach.
        logger.exception("Unparseable schedule restriction on a traces alert", check_id=str(check.id))
        return False


def _evaluate(
    team: Team,
    check: PlatformAlertCheckInput,
    *,
    check_end: datetime,
    now: datetime,
    query_seconds: int,
    cut_short: bool,
    muted: bool,
) -> Decision | None:
    try:
        config = TracesPlatformAlertConfig.model_validate(check.source_config)
    except ValidationError:
        # Saved through the same model, so this is a config an older version accepted.
        return _failed(check, _INVALID_CONFIG, transient=False, check_end=check_end, now=now, muted=muted)
    condition = config.condition
    windows = rolling_check_ranges(
        check_end, condition.window_minutes, check.check_interval_minutes, check.evaluation_periods
    )
    group_by = tuple(check.grouping.keys)
    open_keys = check.open_keys()
    try:
        result = run_check_query(
            team,
            config,
            windows,
            group_by=group_by,
            open_groups=[labels for key in open_keys if (labels := _labels_of(key)) is not None],
            datapoints_to_alarm=check.datapoints_to_alarm,
            # Room for every open group and a full cap of new ones, so admission sees the worst.
            limit=len(open_keys) + check.grouping.max_instances,
            configuration_id=str(check.id),
            max_execution_time=query_seconds,
        )
    except Exception as error:
        if cut_short and isinstance(error, _OUT_OF_TIME_ERRORS):
            return None
        classified = classify_check_error(error)
        if not classified.is_transient:
            logger.warning("Traces alert query refused", check_id=str(check.id), code=classified.code)
        else:
            logger.exception("Traces alert query failed", check_id=str(check.id))
        return _failed(
            check, classified.user_message, transient=classified.is_transient, check_end=check_end, now=now, muted=muted
        )

    observations = [_observe(condition, group, key=_grouping_key(group, group_by)) for group in result.groups]

    def absent(key: str) -> GroupObservation | None:
        labels = _labels_of(key)
        # The query puts every open group it can name first, so only a hashed key, which keeps no
        # labels, can be cut while it still has requests. Without a cut, absence means no request.
        if result.truncated and labels is None:
            return None
        no_requests = GroupValues(labels=labels or {}, values=window_values_with_no_requests(condition, len(windows)))
        return _observe(condition, no_requests, key=key)

    decision = decide_groups(
        check,
        observations,
        snapshot_of=lambda instance, prior: _snapshot(check, prior, instance),
        policy=POLICY,
        now=now,
        muted=muted,
        absent=absent,
    )
    for verdict in decision.verdicts:
        safe_record(increment_checks, SOURCE.value, verdict.outcome.notification.value)
        if verdict.snapshot.state != verdict.outcome.new_state:
            safe_record(
                increment_state_transition, SOURCE.value, verdict.snapshot.state.value, verdict.outcome.new_state.value
            )
    recorded = decision.as_outcome(
        configuration_id=check.id,
        evaluation_key=_evaluation_key(check, check_end, now),
        grouping=check.grouping,
        query_duration_ms=result.query_duration_ms,
        results_cut=result.truncated,
    )
    moves = {
        verdict.group.grouping_key: (verdict.snapshot.state, verdict.outcome.new_state) for verdict in decision.verdicts
    }
    sends_messages = any(verdict.outcome.notification != NotificationAction.NONE for verdict in decision.verdicts)
    return recorded, _request(check, recorded, moves, sends_messages=sends_messages)


def _observe(condition: TracesPlatformAlertCondition, group: GroupValues, *, key: str) -> GroupObservation:
    current, *prior = derive_breaches(
        group.values, condition.threshold, condition.threshold_operator, len(group.values)
    ) or (False,)
    return GroupObservation(
        grouping_key=key,
        current_breached=current,
        prior_breached=tuple(prior),
        value=group.values[-1] if group.values else None,
        labels=group.labels,
    )


def _grouping_key(group: GroupValues, group_by: Sequence[str]) -> str:
    """The instance key for one group's label values, or the single instance's empty key."""
    if not group_by:
        return ""
    return bounded_grouping_key(json.dumps(group.labels, sort_keys=True, separators=(",", ":")))


def _labels_of(grouping_key: str) -> dict[str, str] | None:
    """The labels `_grouping_key` encoded, or None for a hashed key, which keeps no labels."""
    if is_hashed_grouping_key(grouping_key):
        return None
    try:
        labels = json.loads(grouping_key)
    except ValueError:
        return None
    return labels if isinstance(labels, dict) else None


def _evaluation_key(check: PlatformAlertCheckInput, check_end: datetime, now: datetime) -> str:
    # The slot is in the key because the checkpoint clamp can give two scheduled checks one window end.
    return f"slot:{slot_of(check.next_check_at, now)}|window:{check_end.isoformat()}"


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


def _failed(
    check: PlatformAlertCheckInput, message: str, *, transient: bool, check_end: datetime, now: datetime, muted: bool
) -> Decision:
    """A check that reached no verdict. The machine counts it toward BROKEN unless it is transient."""
    snapshot = _snapshot(check, ())
    outcome = evaluate_alert_check(
        snapshot,
        CheckInput(threshold_breached=False, error_message=message, is_transient_error=transient, muted=muted),
        now,
        policy=POLICY,
    )
    safe_record(increment_checks, SOURCE.value, outcome.notification.value)
    recorded = PlatformAlertOutcome.ungrouped(
        configuration_id=check.id,
        evaluation_key=_evaluation_key(check, check_end, now),
        consecutive_failures=outcome.consecutive_failures,
        kind=NOTIFICATION_EVENT_KINDS[outcome.notification],
        new_state=outcome.new_state.value,
        notified=outcome.update_last_notified_at,
        failed=True,
        firing_episode=decide_firing_episode(snapshot, outcome, now, policy=POLICY),
        muted_notification=muted_value(outcome),
        error_message=outcome.error_message,
        disable=outcome.disable,
    )
    return recorded, _request(
        check,
        recorded,
        {"": (snapshot.state, outcome.new_state)},
        sends_messages=outcome.notification != NotificationAction.NONE,
    )


def _request(
    check: PlatformAlertCheckInput,
    recorded: PlatformAlertOutcome,
    moves: dict[str, tuple[AlertState, AlertState]],
    *,
    sends_messages: bool,
) -> AlertDeliveryRequest | None:
    """The delivery for a recorded outcome, or None when it neither announces nor moves a firing.

    A firing that opens or closes needs a delivery even when cooldown or mute held the message,
    because a paging destination needs one resolve for every trigger.
    """
    actions = {
        key: action
        for key, (before, after) in moves.items()
        if (action := decide_incident_action(before, after, policy=POLICY)) is not None
    }
    if actions and not has_incident_destination(team_id=check.team_id, configuration_id=check.id):
        actions = {}
    if not sends_messages and not actions:
        return None
    return AlertDeliveryRequest(
        source=SOURCE,
        team_id=check.team_id,
        configuration_id=str(check.id),
        evaluation_key=recorded.evaluation_key,
        destination_alert_id=str(check.destination_alert_id),
        event_ids_by_kind=EVENT_IDS_BY_KIND,
        event_ids_by_incident_action=EVENT_IDS_BY_INCIDENT_ACTION,
        incident_actions=actions,
        sends_messages=sends_messages,
        source_alert_url=alert_url(check.team_id, check.id),
        owned_by_platform=check.owned_by_platform,
        overflowed=recorded.overflowed,
        overflow_is_lower_bound=recorded.overflow_is_lower_bound,
        parts=delivery_parts(recorded, actions),
    )


def _collect(decided: Sequence[Decision], *, team_id: int, slot: str, past_budget: int) -> SourceBatchEvaluation:
    """The batch, held to one payload. A check past the query budget or the payload keeps its due time."""
    outcomes: list[PlatformAlertOutcome] = []
    deliveries: list[AlertDeliveryRequest] = []
    deferred = 0
    spent = 0
    for outcome, delivery in decided:
        size = payload_bytes(outcome) + (payload_bytes(delivery) if delivery is not None else 0)
        if spent + size > MAX_BATCH_PAYLOAD_BYTES:
            deferred += 1
            continue
        spent += size
        outcomes.append(outcome)
        if delivery is not None:
            deliveries.append(delivery)
    if past_budget or deferred:
        logger.warning(
            "Deferred traces alert checks", team_id=team_id, slot=slot, past_budget=past_budget, over_payload=deferred
        )
        safe_record(increment_checks_deferred, SOURCE.value, past_budget + deferred)
    return SourceBatchEvaluation(outcomes=tuple(outcomes), deliveries=tuple(deliveries), omitted=past_budget + deferred)
