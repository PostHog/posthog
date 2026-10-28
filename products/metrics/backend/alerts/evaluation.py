"""Evaluation of due metrics alerts on the shared alerts platform.

Each check sends its PromQL expression to Snuffle as one instant query, at the check's due time
held back to the ingestion checkpoint. Each series the query returns is compared with the
condition. Under grouping by result labels, each distinct set of grouping label values is a group.
Without grouping, the alert has one group that breaches when any series does.

A series the query no longer returns resolves its group, as it does in Prometheus. A series whose
value is not a number reaches no verdict, so its group keeps its state.

This reads and decides. It writes nothing, so a retried attempt reads the same due checks and makes
the same decisions. The platform records the outcomes in its own activity.
"""

import json
import math
import time
import operator
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any, Final

import structlog
from pydantic import ValidationError

from posthog.dataclasses import frozen
from posthog.models import Team

from products.alerts.backend.facade.destinations import configured_destination_template_ids
from products.alerts_platform.backend.facade.api import due_checks, slot_of
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    GroupingMode,
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
from products.alerts_platform.backend.facade.scheduling import is_utc_datetime_blocked, parse_blocked_windows_tuples
from products.metrics.backend.alerts.checkpoint import evaluation_time, fetch_live_metrics_checkpoint
from products.metrics.backend.alerts.destinations import EVENT_IDS_BY_INCIDENT_ACTION, EVENT_IDS_BY_KIND
from products.metrics.backend.alerts.source_config import MetricsPlatformAlertCondition, MetricsPlatformAlertConfig
from products.metrics.backend.alerts.wording import alert_url
from products.metrics.backend.promql import PromQLQueryError, snuffle_payload

logger = structlog.get_logger(__name__)

SOURCE: Final = SourceKind.METRICS
POLICY: Final = PLATFORM_DEFAULT_ALERT_POLICY

# The batch's query time, which `EVALUATE_START_TO_CLOSE` in the workflow sits above. Checks run one
# after another, and a check the budget has no room for keeps its due time for a later tick.
BATCH_QUERY_BUDGET_SECONDS: Final = 25
# No single query may spend the whole budget, or the first slow one starves the rest.
MAX_QUERY_SECONDS: Final = 10
# Below this there is no point starting another query.
MIN_QUERY_SECONDS: Final = 2
CHECKPOINT_QUERY_SECONDS: Final = 5
# Ten times the most groups a configuration can hold. A query past it is refused before its series
# are judged, so one high-cardinality expression cannot exhaust the worker.
MAX_SERIES: Final = 1000

_UNEXPECTED_ERROR: Final = "Alert check failed unexpectedly. PostHog has been notified."
_INVALID_CONFIG: Final = "The alert's configuration is no longer valid. Edit the alert to fix it."

_COMPARE: Final[dict[str, Callable[[float, float], bool]]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}

Decision = tuple[PlatformAlertOutcome, AlertDeliveryRequest | None]


@frozen
class _Sample:
    labels: dict[str, str]
    # None for a sample that is not a number, such as the result of 0/0.
    value: float | None


def evaluate_metrics_alert_batch(team_id: int, slot: str, cutoff: datetime) -> SourceBatchEvaluation:
    """Evaluates one batch key of metrics alerts against the tick's cutoff."""
    started_at = time.monotonic()
    checks = due_checks(team_id, SOURCE.value, slot, cutoff)
    if not checks:
        return SourceBatchEvaluation(outcomes=(), deliveries=())
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return SourceBatchEvaluation(outcomes=(), deliveries=())

    checkpoint = _checkpoint(team)
    deadline = started_at + BATCH_QUERY_BUDGET_SECONDS
    decided: list[Decision] = []
    for check in checks:
        remaining = deadline - time.monotonic()
        if remaining < MIN_QUERY_SECONDS:
            break
        at = evaluation_time(check.next_check_at or cutoff, checkpoint)
        decided.append(
            _evaluate(
                team,
                check,
                at=at,
                now=cutoff,
                query_seconds=min(MAX_QUERY_SECONDS, remaining),
                muted=_in_quiet_hours(check, cutoff, team.timezone),
            )
        )
    evaluation = _collect(decided, team_id=team_id, slot=slot, past_budget=len(checks) - len(decided))
    safe_record(record_batch_duration, SOURCE.value, int((time.monotonic() - started_at) * 1000))
    return evaluation


def _checkpoint(team: Team) -> datetime | None:
    try:
        return fetch_live_metrics_checkpoint(team, max_execution_time=CHECKPOINT_QUERY_SECONDS)
    except Exception:
        # Without a checkpoint the check reads at its due time, as it would with a fresh one.
        logger.exception("Failed to fetch the metrics ingestion checkpoint", team_id=team.id)
        return None


def _in_quiet_hours(check: PlatformAlertCheckInput, now: datetime, tz_name: str) -> bool:
    try:
        return is_utc_datetime_blocked(now, tz_name, parse_blocked_windows_tuples(check.schedule_restriction))
    except Exception:
        # A restriction that cannot be read must not hold back a breach.
        logger.exception("Unparseable schedule restriction on a metrics alert", check_id=str(check.id))
        return False


def _evaluate(
    team: Team, check: PlatformAlertCheckInput, *, at: datetime, now: datetime, query_seconds: float, muted: bool
) -> Decision:
    started_at = time.monotonic()
    try:
        config = MetricsPlatformAlertConfig.model_validate(check.source_config)
    except ValidationError:
        # Saved through the same model, so this is a config an older version accepted.
        return _failed(check, _INVALID_CONFIG, transient=False, now=now, muted=muted)
    try:
        samples = _query(team, config.query, at=at, timeout_seconds=query_seconds)
    except PromQLQueryError as error:
        return _failed(check, str(error), transient=error.transient, now=now, muted=muted)
    except Exception:
        logger.exception("Failed to evaluate a metrics alert", check_id=str(check.id))
        return _failed(check, _UNEXPECTED_ERROR, transient=True, now=now, muted=muted)
    duration_ms = int((time.monotonic() - started_at) * 1000)

    observations, unknown = _observations(check, config.condition, samples)
    decision = decide_groups(
        check,
        observations,
        snapshot_of=lambda instance, _prior: _snapshot(check, instance),
        policy=POLICY,
        now=now,
        muted=muted,
        # A group with no number this check keeps its state. One the query no longer returns resolves.
        absent=lambda key: None if key in unknown else GroupObservation(grouping_key=key, current_breached=False),
    )
    for verdict in decision.verdicts:
        safe_record(increment_checks, SOURCE.value, verdict.outcome.notification.value)
        if verdict.snapshot.state != verdict.outcome.new_state:
            safe_record(
                increment_state_transition, SOURCE.value, verdict.snapshot.state.value, verdict.outcome.new_state.value
            )
    recorded = decision.as_outcome(
        configuration_id=check.id,
        evaluation_key=_evaluation_key(check, now),
        grouping=check.grouping,
        query_duration_ms=duration_ms,
        results_cut=False,
    )
    moves = {
        verdict.group.grouping_key: (verdict.snapshot.state, verdict.outcome.new_state) for verdict in decision.verdicts
    }
    sends_messages = any(verdict.outcome.notification != NotificationAction.NONE for verdict in decision.verdicts)
    return recorded, _request(check, recorded, moves, sends_messages=sends_messages)


def _query(team: Team, expr: str, *, at: datetime, timeout_seconds: float) -> list[_Sample]:
    """The series one PromQL instant query returns at `at`."""
    payload = snuffle_payload(
        team,
        "POST",
        "/api/v1/query",
        data={"query": expr, "time": str(at.timestamp()), "timeout": f"{int(timeout_seconds)}s"},
        timeout=timeout_seconds,
    )

    data = payload.get("data") or {}
    result_type = data.get("resultType")
    result: Any = data.get("result")
    if result_type == "scalar":
        return [_Sample(labels={}, value=_number(result[1]))] if result else []
    if result_type != "vector":
        raise PromQLQueryError(f"A metrics alert query must return an instant vector or a scalar, not a {result_type}.")
    if len(result or []) > MAX_SERIES:
        raise PromQLQueryError(
            f"The query returned more than {MAX_SERIES} series. Aggregate it, for example with sum by (...)."
        )
    samples: list[_Sample] = []
    for series in result or []:
        # `__name__` stays, so an alert can group by it.
        labels = {str(key): str(value) for key, value in (series.get("metric") or {}).items()}
        sample = series.get("value") or [None, None]
        samples.append(_Sample(labels=labels, value=_number(sample[1])))
    return samples


def _number(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _breached(condition: MetricsPlatformAlertCondition, value: float | None) -> bool | None:
    """Whether a sample breaches, or None when its value reaches no verdict."""
    if condition.kind == "present":
        return True
    # The config model requires both for a threshold condition.
    if value is None or condition.operator is None or condition.threshold is None:
        return None
    return _COMPARE[condition.operator](value, condition.threshold)


def _observations(
    check: PlatformAlertCheckInput, condition: MetricsPlatformAlertCondition, samples: Sequence[_Sample]
) -> tuple[list[GroupObservation], set[str]]:
    """One observation per sample, and the keys of the groups held without a verdict.

    A group with a sample that has no number is held, unless another of its samples breaches. A healthy
    sample beside it does not show that the unknown one recovered.
    """
    by_labels = check.grouping.mode == GroupingMode.BY_RESULT_LABELS
    observations: list[GroupObservation] = []
    unknown: set[str] = set()
    for sample in samples:
        if by_labels:
            labels = {key: sample.labels.get(key, "") for key in check.grouping.keys}
        else:
            labels = {key: value for key, value in sample.labels.items() if key != "__name__"}
        key = _grouping_key_of(labels) if by_labels else ""
        breached = _breached(condition, sample.value)
        if breached is None:
            unknown.add(key)
            continue
        observations.append(
            GroupObservation(grouping_key=key, current_breached=breached, value=sample.value, labels=labels)
        )
    breaching = {observation.grouping_key for observation in observations if observation.current_breached}
    held = unknown - breaching
    return [observation for observation in observations if observation.grouping_key not in held], held


def _grouping_key_of(labels: dict[str, str]) -> str:
    """The instance key for one group's label values."""
    return bounded_grouping_key(json.dumps(labels, sort_keys=True, separators=(",", ":")))


def _evaluation_key(check: PlatformAlertCheckInput, now: datetime) -> str:
    return f"slot:{slot_of(check.next_check_at, now)}"


def _snapshot(check: PlatformAlertCheckInput, instance: InstanceCheckState) -> AlertSnapshot:
    return AlertSnapshot(
        state=AlertState(instance.state),
        cooldown=timedelta(minutes=check.cooldown_minutes),
        last_notified_at=instance.last_notified_at,
        snooze_until=instance.snooze_until,
        consecutive_failures=check.consecutive_failures,
        firing_started_at=instance.firing_started_at,
    )


def _failed(check: PlatformAlertCheckInput, message: str, *, transient: bool, now: datetime, muted: bool) -> Decision:
    """A check that reached no verdict. The machine counts it toward BROKEN unless it is transient."""
    snapshot = _snapshot(check, check.instance())
    outcome = evaluate_alert_check(
        snapshot,
        CheckInput(threshold_breached=False, error_message=message, is_transient_error=transient, muted=muted),
        now,
        policy=POLICY,
    )
    safe_record(increment_checks, SOURCE.value, outcome.notification.value)
    recorded = PlatformAlertOutcome.ungrouped(
        configuration_id=check.id,
        evaluation_key=_evaluation_key(check, now),
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
    destination_alert_id = str(check.destination_alert_id)
    actions = {
        key: action
        for key, (before, after) in moves.items()
        if (action := decide_incident_action(before, after, policy=POLICY)) is not None
    }
    if actions and not configured_destination_template_ids(
        team_id=check.team_id,
        alert_id=destination_alert_id,
        allowed_event_ids=tuple(EVENT_IDS_BY_INCIDENT_ACTION.values()),
    ):
        actions = {}
    if not sends_messages and not actions:
        return None
    return AlertDeliveryRequest(
        source=SOURCE,
        team_id=check.team_id,
        configuration_id=str(check.id),
        evaluation_key=recorded.evaluation_key,
        destination_alert_id=destination_alert_id,
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
            "Deferred metrics alert checks", team_id=team_id, slot=slot, past_budget=past_budget, over_payload=deferred
        )
        safe_record(increment_checks_deferred, SOURCE.value, past_budget + deferred)
    return SourceBatchEvaluation(outcomes=tuple(outcomes), deliveries=tuple(deliveries), omitted=past_budget + deferred)
