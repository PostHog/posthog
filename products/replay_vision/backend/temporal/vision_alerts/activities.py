"""Activities for the replay vision alert check workflow.

Phase layout copies the Logs alert engine: evaluate (no side effects) -> dispatch
(produce the notification, buffered) -> resolve deliveries (flush + ack, roll back
outcomes whose notification never reached the broker) -> save (one transaction).
"""

import dataclasses
from datetime import UTC, datetime, timedelta
from itertools import batched
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Avg, FloatField, Min, QuerySet
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast

import structlog
import temporalio
from pydantic import BaseModel

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async

from products.alerts.backend.destinations import (
    ProduceResult,
    alert_internal_event_delivered,
    flush_alert_internal_events,
    produce_alert_internal_event,
)
from products.alerts.backend.scheduling import is_utc_datetime_blocked, parse_blocked_windows_tuples
from products.replay_vision.backend.alert_destinations import escape_slack_mrkdwn
from products.replay_vision.backend.alert_state_machine import (
    AlertCheckOutcome,
    AlertState,
    CheckResult,
    NotificationAction,
    apply_outcome,
    evaluate_alert_check,
)
from products.replay_vision.backend.alert_utils import (
    advance_next_check_at,
    compute_shard_offset_seconds,
    due_alerts_q,
    next_allowed_check_at,
)
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.vision_alert import (
    DELIVERED_MATCH_RETENTION_DAYS,
    EVENT_RETENTION_DAYS,
    STALE_MATCH_RETENTION_DAYS,
    VisionAlertConfiguration,
    VisionAlertDirection,
    VisionAlertEvent,
    VisionAlertKind,
    VisionAlertMatch,
    VisionAlertMetric,
)
from products.replay_vision.backend.observation_formatting import describe_output
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.vision_actions.synthesis import apply_observation_predicate
from products.replay_vision.backend.temporal.vision_alerts.constants import (
    CLEANUP_BATCH_SIZE,
    MATCH_DESCRIPTOR_MAX_CHARS,
    MATCH_SUMMARY_LINES,
    MAX_ALERTS_PER_BATCH,
    MAX_ALERTS_PER_TICK,
    MAX_DRAIN_ALERTS_PER_TICK,
    MAX_MATCHES_PER_BUNDLE,
    NOTIFICATION_FLUSH_TIMEOUT_SECONDS,
)

logger = structlog.get_logger(__name__)


class CheckVisionAlertsInput(BaseModel):
    pass


class CheckVisionAlertsOutput(BaseModel):
    alerts_checked: int = 0
    alerts_fired: int = 0
    alerts_resolved: int = 0
    alerts_errored: int = 0


class DiscoverDueAlertsInput(BaseModel):
    pass


class DiscoverDueAlertsOutput(BaseModel):
    batches: list[list[str]] = []


class EvaluateAlertBatchInput(BaseModel):
    alert_ids: list[str]


class EvaluateAlertBatchOutput(BaseModel):
    alerts_checked: int = 0
    alerts_fired: int = 0
    alerts_resolved: int = 0
    alerts_errored: int = 0


class CleanupAlertHistoryInput(BaseModel):
    pass


@frozen
class _AlertEvaluation:
    """Phase 1 output: per-alert state-machine result. No Kafka, no writes yet."""

    alert: VisionAlertConfiguration
    outcome: AlertCheckOutcome
    check_result: CheckResult
    state_before: str


@frozen
class _DispatchedAlert:
    """Phase 2 output: notification dispatched (buffered), ready for the save.

    `notification_failed` drives state rollback: the committed outcome reverts to the
    pre-check state so the next cycle re-evaluates and re-tries the notification. The
    failure counter may heal downward but never advance, so the 0 -> 1 error-notify
    edge is not silently consumed.
    """

    evaluation: _AlertEvaluation
    notification_failed: bool
    produce_result: ProduceResult | None = None
    # Disabled, snoozed, or inside quiet hours at dispatch time: no notification, and the
    # alert is excluded from the save so a concurrent control-plane change is not clobbered.
    suppressed: bool = False

    @property
    def committed_outcome(self) -> AlertCheckOutcome:
        if self.notification_failed:
            return dataclasses.replace(
                self.evaluation.outcome,
                new_state=AlertState(self.evaluation.alert.state),
                consecutive_failures=min(
                    self.evaluation.alert.consecutive_failures,
                    self.evaluation.outcome.consecutive_failures,
                ),
            )
        return self.evaluation.outcome


@temporalio.activity.defn
@track_activity()
async def discover_due_vision_alerts_activity(inputs: DiscoverDueAlertsInput) -> DiscoverDueAlertsOutput:
    return await database_sync_to_async(_discover_due, thread_sensitive=False)(inputs)


def _discover_due(inputs: DiscoverDueAlertsInput) -> DiscoverDueAlertsOutput:
    now = datetime.now(UTC)
    # Oldest due first, capped so the workflow result stays far below Temporal's payload
    # limit; the overflow keeps its next_check_at and is picked up next tick.
    due_ids = list(
        VisionAlertConfiguration.all_teams.filter(
            due_alerts_q(now, broken_state=AlertState.BROKEN.value, snoozed_state=AlertState.SNOOZED.value),
            kind=VisionAlertKind.METRIC,
        )
        .order_by("next_check_at", "id")
        .values_list("id", flat=True)[: MAX_ALERTS_PER_TICK + 1]
    )
    if len(due_ids) > MAX_ALERTS_PER_TICK:
        logger.warning("vision_alert.discovery_truncated", cap=MAX_ALERTS_PER_TICK)
        due_ids = due_ids[:MAX_ALERTS_PER_TICK]
    batches = [[str(alert_id) for alert_id in chunk] for chunk in batched(due_ids, MAX_ALERTS_PER_BATCH, strict=False)]
    return DiscoverDueAlertsOutput(batches=batches)


@temporalio.activity.defn
@track_activity()
async def evaluate_vision_alert_batch_activity(inputs: EvaluateAlertBatchInput) -> EvaluateAlertBatchOutput:
    return await database_sync_to_async(_evaluate_batch, thread_sensitive=False)(inputs)


def _evaluate_batch(inputs: EvaluateAlertBatchInput) -> EvaluateAlertBatchOutput:
    now = datetime.now(UTC)
    alerts = list(
        VisionAlertConfiguration.all_teams.filter(id__in=inputs.alert_ids, kind=VisionAlertKind.METRIC)
        .select_related("team", "scanner")
        .order_by("id")
    )

    dispatched: list[_DispatchedAlert] = []
    for alert in alerts:
        evaluation = _evaluate_single_alert(alert, now)
        dispatched.append(_dispatch_for_alert(evaluation, now))

    dispatched = _resolve_notification_deliveries(dispatched)
    to_save = [d for d in dispatched if not d.suppressed]
    saved = _save_outcomes(to_save, now)

    output = EvaluateAlertBatchOutput()
    for d in saved:
        output.alerts_checked += 1
        committed = d.committed_outcome
        if d.evaluation.outcome.error_message is not None:
            output.alerts_errored += 1
        elif not d.notification_failed and committed.notification == NotificationAction.FIRE:
            output.alerts_fired += 1
        elif not d.notification_failed and committed.notification == NotificationAction.RESOLVE:
            output.alerts_resolved += 1
    return output


def _observation_window_qs(
    alert: VisionAlertConfiguration, window_start: datetime, window_end: datetime
) -> QuerySet[ReplayObservation]:
    selection: dict[str, Any] = alert.selection or {}
    queryset = ReplayObservation.objects.filter(
        team_id=alert.team_id,
        scanner_id=alert.scanner_id,
        status=ObservationStatus.SUCCEEDED,
        completed_at__gte=window_start,
        completed_at__lt=window_end,
    )
    return apply_observation_predicate(queryset, selection)


def _evaluate_single_alert(alert: VisionAlertConfiguration, now: datetime) -> _AlertEvaluation:
    """Phase 1: run the observation window query, apply the state machine."""
    window_start = now - timedelta(days=alert.window_days)

    check_result: CheckResult
    try:
        queryset = _observation_window_qs(alert, window_start, now)
        if alert.metric == VisionAlertMetric.AVG_SCORE:
            # Cast the JSONB score to float and average it; observations without a
            # score (non-scorers) become NULL and fall out of the average.
            metric_value = queryset.annotate(
                _score=Cast(
                    KeyTextTransform("score", KeyTextTransform("model_output", "scanner_result")),
                    output_field=FloatField(),
                )
            ).aggregate(avg=Avg("_score"))["avg"]
        else:
            metric_value = float(queryset.count())

        if metric_value is None:
            # An empty window has no average; neither direction can breach.
            check_result = CheckResult(metric_value=None, threshold_breached=False, is_inconclusive=True)
        else:
            threshold = float(alert.threshold or 0)
            if alert.direction == VisionAlertDirection.BELOW:
                breached = metric_value <= threshold
            else:
                breached = metric_value >= threshold
            check_result = CheckResult(metric_value=metric_value, threshold_breached=breached)
    except Exception as e:
        capture_exception(e, {"alert_id": str(alert.id)})
        logger.warning("vision_alert.check_query_failed", alert_id=str(alert.id), team_id=alert.team_id, error=str(e))
        check_result = CheckResult(
            metric_value=None,
            threshold_breached=False,
            error_message="The alert check query failed.",
            is_transient_error=isinstance(e, OperationalError),
        )

    outcome = evaluate_alert_check(alert.to_snapshot(), check_result, now)
    return _AlertEvaluation(alert=alert, outcome=outcome, check_result=check_result, state_before=alert.state)


def _dispatch_for_alert(evaluation: _AlertEvaluation, now: datetime) -> _DispatchedAlert:
    """Phase 2: re-check current state, defer quiet-hours alerts, or dispatch.

    The evaluation ran on a snapshot from discovery; a user may have disabled or snoozed
    the alert since. Re-read those fields fresh and suppress instead of paging. Any lock
    closes before the produce: nothing may hold an alert row lock across Kafka work, or
    every observation-completion insert against that alert's FK stalls.
    """
    current = (
        VisionAlertConfiguration.all_teams.filter(id=evaluation.alert.id)
        .values("enabled", "snooze_until", "schedule_restriction")
        .first()
    )
    if (
        current is None
        or not current["enabled"]
        or (current["snooze_until"] is not None and current["snooze_until"] > now)
    ):
        return _DispatchedAlert(evaluation=evaluation, notification_failed=False, suppressed=True)

    if current["schedule_restriction"]:
        with transaction.atomic():
            current_alert = (
                VisionAlertConfiguration.all_teams.select_for_update(of=("self",))
                .select_related("team")
                .get(id=evaluation.alert.id)
            )
            try:
                next_check_at = next_allowed_check_at(
                    now,
                    team_timezone=current_alert.team.timezone,
                    schedule_restriction=current_alert.schedule_restriction,
                )
            except Exception as e:
                logger.exception(
                    "vision_alert.invalid_quiet_hours",
                    alert_id=str(current_alert.id),
                    team_id=current_alert.team_id,
                    error=str(e),
                )
                return _DispatchedAlert(evaluation=evaluation, notification_failed=False, suppressed=True)
            if next_check_at > now:
                current_alert.next_check_at = next_check_at
                current_alert.save(update_fields=["next_check_at", "updated_at"])
                return _DispatchedAlert(evaluation=evaluation, notification_failed=False, suppressed=True)

    produce_result = _dispatch_notification(evaluation, now)
    enqueue_failed = evaluation.outcome.notification != NotificationAction.NONE and produce_result is None
    return _DispatchedAlert(evaluation=evaluation, notification_failed=enqueue_failed, produce_result=produce_result)


def _notification_uuid(evaluation: _AlertEvaluation) -> str:
    """Deterministic per check cycle, so an activity retry that re-produces the same
    notification dedupes at ingestion while the next cycle gets a fresh id. Anchored on
    pre-advance columns that only move when a cycle saves, so a retry crossing a
    wall-clock boundary cannot mint a second uuid."""
    alert = evaluation.alert
    anchor_dt = alert.next_check_at or alert.last_checked_at or alert.created_at
    action = evaluation.outcome.notification.value
    return str(uuid5(NAMESPACE_URL, f"vision-alert:{alert.id}:{action}:{anchor_dt.isoformat()}"))


def _dispatch_notification(evaluation: _AlertEvaluation, now: datetime) -> ProduceResult | None:
    action = evaluation.outcome.notification
    if action == NotificationAction.NONE:
        return None

    alert = evaluation.alert
    event_uuid = _notification_uuid(evaluation)
    log = logger.bind(alert_id=str(alert.id), alert_name=alert.name, team_id=alert.team_id)
    if action == NotificationAction.FIRE:
        result = _emit_alert_event(alert, "$replay_vision_alert_firing", evaluation.check_result, now, event_uuid)
        log.info("vision_alert.fired", metric_value=evaluation.check_result.metric_value, enqueued=result is not None)
    elif action == NotificationAction.RESOLVE:
        result = _emit_alert_event(alert, "$replay_vision_alert_resolved", evaluation.check_result, now, event_uuid)
        log.info("vision_alert.resolved", enqueued=result is not None)
    elif action == NotificationAction.ERROR:
        result = _emit_failure_event(
            alert, "$replay_vision_alert_errored", evaluation.outcome, now, event_uuid, message_key="error_message"
        )
        log.info("vision_alert.errored", consecutive_failures=evaluation.outcome.consecutive_failures)
    elif action == NotificationAction.BROKEN:
        result = _emit_failure_event(
            alert,
            "$replay_vision_alert_auto_disabled",
            evaluation.outcome,
            now,
            event_uuid,
            message_key="last_error_message",
        )
        log.warning("vision_alert.broken", consecutive_failures=evaluation.outcome.consecutive_failures)
    else:
        raise ValueError(f"Unhandled NotificationAction: {action!r}")
    return result


def _resolve_notification_deliveries(dispatched: list[_DispatchedAlert]) -> list[_DispatchedAlert]:
    """Phase 2.5: flush the producer and fold delivery failures into `notification_failed`.

    Flush failures are swallowed: per-result checks classify each alert individually,
    and a save with rolled-back state beats no save at all.
    """
    if all(d.produce_result is None for d in dispatched):
        return dispatched

    flush_alert_internal_events(NOTIFICATION_FLUSH_TIMEOUT_SECONDS)

    resolved: list[_DispatchedAlert] = []
    for d in dispatched:
        if d.produce_result is None:
            resolved.append(d)
        elif alert_internal_event_delivered(
            d.produce_result,
            team_id=d.evaluation.alert.team_id,
            alert_id=str(d.evaluation.alert.id),
            event_name=d.evaluation.outcome.notification.value,
        ):
            resolved.append(d)
        else:
            resolved.append(dataclasses.replace(d, notification_failed=True))
    return resolved


def _stage_alert_for_save(dispatched: _DispatchedAlert, now: datetime) -> tuple[list[str], VisionAlertEvent]:
    """Mutate the in-memory alert for bulk_update; return update fields and the CHECK row.

    Unlike Logs, a CHECK event row is written on every check: it is what feeds the
    N-of-M window (`get_recent_breaches`) and the history chart, and vision volumes
    make the rows cheap.
    """
    evaluation = dispatched.evaluation
    alert = evaluation.alert
    committed = dispatched.committed_outcome

    update_fields = apply_outcome(alert, committed)
    alert.last_checked_at = now
    # bulk_update does not apply auto_now; stamp updated_at explicitly.
    alert.updated_at = now
    next_check_at = advance_next_check_at(
        alert.next_check_at,
        alert.check_interval_minutes,
        now,
        shard_offset_seconds=compute_shard_offset_seconds(alert.id, alert.check_interval_minutes),
    )
    try:
        alert.next_check_at = next_allowed_check_at(
            next_check_at,
            team_timezone=alert.team.timezone,
            schedule_restriction=alert.schedule_restriction,
        )
    except Exception as e:
        logger.exception(
            "vision_alert.invalid_quiet_hours_at_save", alert_id=str(alert.id), team_id=alert.team_id, error=str(e)
        )
        alert.next_check_at = next_check_at
    update_fields.extend(["last_checked_at", "next_check_at", "updated_at"])

    if (
        not dispatched.notification_failed
        and evaluation.outcome.notification != NotificationAction.NONE
        and evaluation.outcome.update_last_notified_at
    ):
        alert.last_notified_at = now
        update_fields.append("last_notified_at")

    event = VisionAlertEvent(
        alert=alert,
        metric_value=evaluation.check_result.metric_value,
        threshold_breached=evaluation.check_result.threshold_breached,
        state_before=evaluation.state_before,
        state_after=committed.new_state.value,
        error_message=evaluation.outcome.error_message,
    )
    return update_fields, event


_UPDATE_FIELDS: list[str] = [
    "state",
    "consecutive_failures",
    "last_checked_at",
    "next_check_at",
    "last_notified_at",
    "updated_at",
]


def _save_outcomes(dispatched: list[_DispatchedAlert], now: datetime) -> list[_DispatchedAlert]:
    """Phase 3: persist outcomes via one bulk_create + one bulk_update; on
    IntegrityError, fall back to per-alert saves with the already-staged data so
    `next_check_at` is not advanced twice."""
    if not dispatched:
        return []

    staged: list[tuple[_DispatchedAlert, list[str], VisionAlertEvent]] = []
    try:
        with transaction.atomic():
            # Ordered locking avoids deadlock with concurrent batches; the fresh re-read
            # drops alerts a user disabled, snoozed, or reset during the dispatch window,
            # so the control-plane transition wins over the stale evaluated state.
            current_rows = {
                row["id"]: row
                for row in VisionAlertConfiguration.all_teams.select_for_update()
                .filter(id__in=[d.evaluation.alert.id for d in dispatched])
                .order_by("id")
                .values("id", "enabled", "state", "schedule_restriction")
            }
            for d in dispatched:
                current = current_rows.get(d.evaluation.alert.id)
                if current is None or not current["enabled"] or current["state"] != d.evaluation.state_before:
                    logger.info(
                        "vision_alert.save_skipped_concurrent_transition",
                        alert_id=str(d.evaluation.alert.id),
                        state_before=d.evaluation.state_before,
                        current_state=current["state"] if current else None,
                    )
                    continue
                d.evaluation.alert.schedule_restriction = current["schedule_restriction"]
                update_fields, event = _stage_alert_for_save(d, now)
                staged.append((d, update_fields, event))

            VisionAlertEvent.objects.bulk_create([event for _, _, event in staged])
            VisionAlertConfiguration.all_teams.bulk_update(
                [d.evaluation.alert for d, _, _ in staged], fields=_UPDATE_FIELDS
            )
        return [d for d, _, _ in staged]
    except IntegrityError as e:
        logger.warning("vision_alert.bulk_save_integrity_error", error=str(e), batch_size=len(dispatched))
        capture_exception(e, {"batch_size": len(dispatched), "fallback": "per_alert"})

    saved: list[_DispatchedAlert] = []
    for d, update_fields, event in staged:
        try:
            with transaction.atomic():
                event.save()
                d.evaluation.alert.save(update_fields=update_fields)
            saved.append(d)
        except Exception as e:
            logger.exception("vision_alert.per_alert_save_failed", alert_id=str(d.evaluation.alert.id))
            capture_exception(e, {"alert_id": str(d.evaluation.alert.id), "phase": "per_alert_fallback"})
    return saved


def _metric_label(alert: VisionAlertConfiguration) -> str:
    return "average score" if alert.metric == VisionAlertMetric.AVG_SCORE else "matching observations"


def _window_label(alert: VisionAlertConfiguration) -> str:
    return "24 hours" if alert.window_days == 1 else f"{alert.window_days} days"


def _direction_label(alert: VisionAlertConfiguration) -> str:
    return "at or below" if alert.direction == VisionAlertDirection.BELOW else "at or above"


def _base_properties(alert: VisionAlertConfiguration, now: datetime) -> dict:
    return {
        "alert_id": str(alert.id),
        "alert_name": alert.name,
        "team_id": alert.team_id,
        "scanner_id": str(alert.scanner_id),
        "scanner_name": alert.scanner.name,
        "scanner_name_mrkdwn": escape_slack_mrkdwn(alert.scanner.name),
        "triggered_at": now.isoformat(),
    }


def _emit_alert_event(
    alert: VisionAlertConfiguration, event_name: str, check_result: CheckResult, now: datetime, event_uuid: str
) -> ProduceResult | None:
    properties = {
        **_base_properties(alert, now),
        "metric": alert.metric,
        "metric_label": _metric_label(alert),
        "metric_value": check_result.metric_value,
        "threshold": alert.threshold,
        "direction": _direction_label(alert),
        "window_days": alert.window_days,
        "window_label": _window_label(alert),
    }
    return produce_alert_internal_event(
        team_id=alert.team_id, event_name=event_name, properties=properties, timestamp=now, uuid=event_uuid
    )


def _emit_failure_event(
    alert: VisionAlertConfiguration,
    event_name: str,
    outcome: AlertCheckOutcome,
    now: datetime,
    event_uuid: str,
    *,
    message_key: str,
) -> ProduceResult | None:
    properties = {
        **_base_properties(alert, now),
        "consecutive_failures": outcome.consecutive_failures,
        message_key: outcome.error_message or "",
    }
    return produce_alert_internal_event(
        team_id=alert.team_id, event_name=event_name, properties=properties, timestamp=now, uuid=event_uuid
    )


@temporalio.activity.defn
@track_activity()
async def cleanup_vision_alert_history_activity(inputs: CleanupAlertHistoryInput) -> int:
    return await database_sync_to_async(_cleanup_history, thread_sensitive=False)(inputs)


def _cleanup_history(inputs: CleanupAlertHistoryInput) -> int:
    """Bounded retention sweep, one small batch per tick: old check-history rows,
    delivered outbox rows past retention, and stale undelivered outbox rows
    (alerts disabled or deleted between insert and drain)."""
    now = datetime.now(UTC)
    deleted = 0

    event_ids = list(
        VisionAlertEvent.objects.filter(created_at__lt=now - timedelta(days=EVENT_RETENTION_DAYS)).values_list(
            "id", flat=True
        )[:CLEANUP_BATCH_SIZE]
    )
    if event_ids:
        deleted += VisionAlertEvent.objects.filter(id__in=event_ids).delete()[0]

    delivered_ids = list(
        VisionAlertMatch.all_teams.filter(
            delivered_at__lt=now - timedelta(days=DELIVERED_MATCH_RETENTION_DAYS)
        ).values_list("id", flat=True)[:CLEANUP_BATCH_SIZE]
    )
    stale_ids = list(
        VisionAlertMatch.all_teams.filter(
            delivered_at__isnull=True, created_at__lt=now - timedelta(days=STALE_MATCH_RETENTION_DAYS)
        ).values_list("id", flat=True)[:CLEANUP_BATCH_SIZE]
    )
    match_ids = delivered_ids + stale_ids
    if match_ids:
        deleted += VisionAlertMatch.all_teams.filter(id__in=match_ids).delete()[0]

    return deleted


class DrainMatchesInput(BaseModel):
    pass


class DrainMatchesOutput(BaseModel):
    alerts_notified: int = 0
    matches_delivered: int = 0


@temporalio.activity.defn
@track_activity()
async def drain_vision_alert_matches_activity(inputs: DrainMatchesInput) -> DrainMatchesOutput:
    return await database_sync_to_async(_drain_matches, thread_sensitive=False)(inputs)


@frozen
class _DrainedBundle:
    alert: VisionAlertConfiguration
    match_ids: list[Any]
    produce_result: ProduceResult | None


def _drain_matches(inputs: DrainMatchesInput) -> DrainMatchesOutput:
    """Bundle undelivered match rows into one notification per alert and stamp them
    delivered only after the producer acks.

    No alert-row locks are taken here: match alerts have no lifecycle state to mutate,
    and holding one across produce/flush would stall the observation-completion hook's
    FK inserts against the same alert row. Stamping targets the explicitly drained row
    IDs, never `delivered_at IS NULL`, so rows inserted mid-drain wait for the next tick.
    """
    now = datetime.now(UTC)
    # Per-alert fairness: pick the alerts with the oldest undelivered rows, then bound
    # each bundle separately, so one high-volume alert cannot fill a global slice and
    # starve the rest. Disabled and snoozed alerts are excluded in SQL so their held
    # rows cannot occupy the alert budget either.
    due_alert_ids = list(
        VisionAlertMatch.all_teams.filter(delivered_at__isnull=True, alert__enabled=True)
        .exclude(alert__snooze_until__gt=now)
        .values("alert_id")
        .annotate(oldest=Min("created_at"))
        .order_by("oldest")
        .values_list("alert_id", flat=True)[:MAX_DRAIN_ALERTS_PER_TICK]
    )
    if not due_alert_ids:
        return DrainMatchesOutput()

    alerts = (
        VisionAlertConfiguration.all_teams.filter(id__in=due_alert_ids, kind=VisionAlertKind.MATCH)
        .select_related("team", "scanner")
        .order_by("id")
    )

    bundles: list[_DrainedBundle] = []
    for alert in alerts:
        if not alert.enabled:
            continue  # Cleanup reaps the rows; delivering for a disabled alert is wrong.
        if alert.snooze_until is not None and alert.snooze_until > now:
            continue  # Hold: matches accumulate and deliver as one bundle after the snooze.
        try:
            if is_utc_datetime_blocked(
                now, alert.team.timezone, parse_blocked_windows_tuples(alert.schedule_restriction)
            ):
                continue  # Quiet hours: hold until the window ends.
        except Exception as e:
            logger.exception("vision_alert.drain_invalid_quiet_hours", alert_id=str(alert.id), error=str(e))
            continue

        # A huge backlog splits across ticks: an oversized event payload would fail the
        # produce forever, and the leftovers keep their created_at order.
        rows = list(
            VisionAlertMatch.all_teams.filter(alert_id=alert.id, delivered_at__isnull=True)
            .order_by("created_at", "id")
            .values_list("id", "observation_id")[:MAX_MATCHES_PER_BUNDLE]
        )
        if not rows:
            continue
        produce_result = _emit_match_event(alert, rows, now)
        bundles.append(
            _DrainedBundle(
                alert=alert,
                match_ids=[row_id for row_id, _ in rows],
                produce_result=produce_result,
            )
        )

    if any(b.produce_result is not None for b in bundles):
        flush_alert_internal_events(NOTIFICATION_FLUSH_TIMEOUT_SECONDS)

    output = DrainMatchesOutput()
    for bundle in bundles:
        if bundle.produce_result is None:
            continue  # Enqueue failed; rows stay undelivered and re-emit next tick.
        if not alert_internal_event_delivered(
            bundle.produce_result,
            team_id=bundle.alert.team_id,
            alert_id=str(bundle.alert.id),
            event_name="$replay_vision_alert_match",
        ):
            continue
        VisionAlertMatch.all_teams.filter(id__in=bundle.match_ids).update(delivered_at=now)
        output.alerts_notified += 1
        output.matches_delivered += len(bundle.match_ids)
    return output


def _emit_match_event(
    alert: VisionAlertConfiguration, rows: list[tuple[Any, Any]], now: datetime
) -> ProduceResult | None:
    observation_ids = [str(observation_id) for _, observation_id in rows]
    summary_rows = ReplayObservation.objects.filter(
        team_id=alert.team_id, id__in=observation_ids[:MATCH_SUMMARY_LINES]
    ).values_list("id", "scanner_result", "completed_at")
    by_id = {str(row_id): (scanner_result, completed_at) for row_id, scanner_result, completed_at in summary_rows}
    lines: list[str] = []
    for observation_id in observation_ids[:MATCH_SUMMARY_LINES]:
        scanner_result, completed_at = by_id.get(observation_id, (None, None))
        model_output = (scanner_result or {}).get("model_output") or {}
        descriptor = escape_slack_mrkdwn((describe_output(model_output) or "observation")[:MATCH_DESCRIPTOR_MAX_CHARS])
        stamp = f"({completed_at:%Y-%m-%d %H:%M} UTC) " if completed_at else ""
        lines.append(f"- {stamp}{descriptor}")
    if len(observation_ids) > MATCH_SUMMARY_LINES:
        lines.append(f"- and {len(observation_ids) - MATCH_SUMMARY_LINES} more")

    # Deterministic uuid over the drained row set: an identical-batch retry (crash
    # after ack, before the stamp, with no new rows) dedupes at ingestion.
    event_uuid = uuid5(NAMESPACE_URL, f"vision-alert-match:{alert.id}:{','.join(sorted(str(m) for m, _ in rows))}")

    properties = {
        **_base_properties(alert, now),
        "matched_count": len(rows),
        "observation_ids": observation_ids,
        "summary": "\n".join(lines),
    }
    return produce_alert_internal_event(
        team_id=alert.team_id,
        event_name="$replay_vision_alert_match",
        properties=properties,
        timestamp=now,
        uuid=str(event_uuid),
    )
