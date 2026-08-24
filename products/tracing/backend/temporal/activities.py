"""Temporal activities for tracing alerting.

v1 deliberately has no cohort/batch query grouping (see `alert_check_query.py`):
each alert in a batch still runs its own ClickHouse query. `MAX_ALERTS_PER_BATCH`
only controls Temporal fan-out granularity. Quiet hours are enforced at dispatch
time, not pre-filtered during discovery like logs does — a blocked alert still
runs its ClickHouse query every cycle until dispatch defers it, which is
correct but not as cheap; that discovery-side skip is a deferred optimization,
not a correctness gap.
"""

import time
import dataclasses
from datetime import UTC, datetime, timedelta

from django.db import transaction
from django.db.models import QuerySet

import structlog
import temporalio.activity

from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.client import ProduceResult
from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async_pool

from products.alerts.backend.alert_error_classifier import (
    AlertErrorCode,
    classify as classify_alert_error,
)
from products.alerts.backend.destinations import (
    alert_internal_event_delivered,
    flush_alert_internal_events,
    produce_alert_internal_event,
)
from products.tracing.backend.alert_check_query import AlertCheckQuery, BucketedCount, rolling_check_lookback_minutes
from products.tracing.backend.alert_state_machine import (
    AlertCheckOutcome,
    CheckResult,
    NotificationAction,
    apply_outcome,
    evaluate_alert_check,
)
from products.tracing.backend.alert_utils import (
    advance_next_check_at,
    compute_shard_offset_seconds,
    due_alerts_q,
    next_allowed_check_at,
)
from products.tracing.backend.models import TracingAlertConfiguration, TracingAlertEvent
from products.tracing.backend.temporal.constants import MAX_ALERTS_PER_BATCH, NOTIFICATION_FLUSH_TIMEOUT_SECONDS

logger = structlog.get_logger(__name__)


def _derive_breaches(
    buckets: list[BucketedCount],
    threshold_count: int,
    threshold_operator: str,
    evaluation_periods: int,
) -> tuple[bool, ...]:
    """Map ASC-ordered bucketed CH counts to a newest-first breach tuple of length M.

    Mirrors `products/logs/backend/temporal/activities.py`'s `_derive_breaches` —
    see that module's docstring for why sparse buckets need padding.
    """
    if threshold_operator == "above":
        actual = tuple(b.count > threshold_count for b in reversed(buckets))
        missing_breach = False
    else:
        actual = tuple(b.count < threshold_count for b in reversed(buckets))
        missing_breach = True
    pad = (missing_breach,) * max(0, evaluation_periods - len(actual))
    return actual + pad


@dataclasses.dataclass(frozen=True)
class CheckAlertsInput:
    pass


@dataclasses.dataclass(frozen=True)
class CheckAlertsOutput:
    alerts_checked: int
    alerts_fired: int
    alerts_resolved: int
    alerts_errored: int


@dataclasses.dataclass(frozen=True)
class DiscoverDueAlertsInput:
    pass


@dataclasses.dataclass(frozen=True)
class DiscoverDueAlertsOutput:
    alert_ids: list[str]
    # Recorded in workflow history so replays chunk identically even if the env
    # var changes between runs.
    batch_size: int


@dataclasses.dataclass(frozen=True)
class EvaluateAlertBatchInput:
    alert_ids: list[str]


@dataclasses.dataclass(frozen=True)
class EvaluateAlertBatchOutput:
    alerts_checked: int
    alerts_fired: int
    alerts_resolved: int
    alerts_errored: int


def _due_alerts_qs(now: datetime) -> QuerySet[TracingAlertConfiguration]:
    # Cross-team scheduler scan — the fail-closed manager has no single ambient
    # team to filter by here, so this is the sanctioned `.unscoped()` escape hatch.
    return TracingAlertConfiguration.objects.unscoped().filter(
        due_alerts_q(
            now,
            broken_state=TracingAlertConfiguration.State.BROKEN,
            snoozed_state=TracingAlertConfiguration.State.SNOOZED,
        )
    )


@temporalio.activity.defn
async def discover_due_tracing_alerts_activity(input: DiscoverDueAlertsInput) -> DiscoverDueAlertsOutput:
    return await database_sync_to_async_pool(_discover_due_alerts_sync)()


def _discover_due_alerts_sync() -> DiscoverDueAlertsOutput:
    now = datetime.now(UTC)
    alert_ids = list(_due_alerts_qs(now).values_list("id", flat=True))
    return DiscoverDueAlertsOutput(
        alert_ids=[str(alert_id) for alert_id in alert_ids],
        batch_size=MAX_ALERTS_PER_BATCH,
    )


@temporalio.activity.defn
async def evaluate_alert_batch_activity(input: EvaluateAlertBatchInput) -> EvaluateAlertBatchOutput:
    return await database_sync_to_async_pool(_evaluate_alert_batch_sync)(input)


def _evaluate_alert_batch_sync(input: EvaluateAlertBatchInput) -> EvaluateAlertBatchOutput:
    now = datetime.now(UTC)
    alerts_checked = 0
    alerts_fired = 0
    alerts_resolved = 0
    alerts_errored = 0

    for alert_id in input.alert_ids:
        try:
            outcome_kind = _evaluate_dispatch_and_save_one_alert(alert_id, now)
        except TracingAlertConfiguration.DoesNotExist:
            # Deleted or disabled between discovery and evaluation — not an error.
            continue
        except Exception as e:
            capture_exception(e, {"alert_id": alert_id, "feature": "tracing_alerting"})
            logger.exception("Unhandled error evaluating tracing alert", alert_id=alert_id, error=str(e))
            alerts_errored += 1
            continue

        alerts_checked += 1
        if outcome_kind == "fired":
            alerts_fired += 1
        elif outcome_kind == "resolved":
            alerts_resolved += 1
        elif outcome_kind == "errored":
            alerts_errored += 1

    return EvaluateAlertBatchOutput(
        alerts_checked=alerts_checked,
        alerts_fired=alerts_fired,
        alerts_resolved=alerts_resolved,
        alerts_errored=alerts_errored,
    )


def _evaluate_dispatch_and_save_one_alert(alert_id: str, now: datetime) -> str:
    """Load, evaluate, dispatch, and save one alert — scoped to its own team.

    Returns one of "fired" / "resolved" / "errored" / "unchanged" / "suppressed"
    (quiet hours) for the caller's stats accounting.
    """
    alert = TracingAlertConfiguration.objects.unscoped().select_related("team").get(id=alert_id)
    with team_scope(alert.team_id, canonical=True):
        return _evaluate_dispatch_and_save_scoped(alert, now)


def _evaluate_dispatch_and_save_scoped(alert: TracingAlertConfiguration, now: datetime) -> str:
    nca = alert.next_check_at if alert.next_check_at is not None else now
    date_to = nca
    date_from = date_to - timedelta(
        minutes=rolling_check_lookback_minutes(
            alert.window_minutes, alert.check_interval_minutes, alert.evaluation_periods
        )
    )

    check_result: CheckResult
    recent_breaches: tuple[bool, ...] = ()
    error_category: AlertErrorCode | None = None
    try:
        query_start = time.perf_counter()
        buckets = AlertCheckQuery(
            team=alert.team,
            alert=alert,
            date_from=date_from,
            date_to=date_to,
        ).execute_rolling_checks(
            nca=date_to,
            window_minutes=alert.window_minutes,
            cadence_minutes=alert.check_interval_minutes,
            period_count=alert.evaluation_periods,
        )
        query_duration_ms = int((time.perf_counter() - query_start) * 1000)

        breaches = _derive_breaches(buckets, alert.threshold_count, alert.threshold_operator, alert.evaluation_periods)
        latest_count = buckets[-1].count if buckets else 0
        check_result = CheckResult(
            result_count=latest_count,
            threshold_breached=breaches[0] if breaches else False,
            query_duration_ms=query_duration_ms,
        )
        recent_breaches = breaches[1:]
    except Exception as e:
        classified = classify_alert_error(e)
        error_category = classified.code
        capture_exception(e, {"alert_id": str(alert.id), "classification": classified.code})
        logger.warning(
            "Tracing alert check query failed",
            alert_id=str(alert.id),
            alert_name=alert.name,
            team_id=alert.team_id,
            error=str(e),
            classification=classified.code,
        )
        check_result = CheckResult(
            result_count=None,
            threshold_breached=False,
            error_message=classified.user_message,
            is_transient_error=classified.is_transient,
        )

    outcome = evaluate_alert_check(alert.to_snapshot(recent_events_breached=recent_breaches), check_result, now)

    with transaction.atomic():
        current_alert = (
            TracingAlertConfiguration.objects.select_for_update(of=("self",)).select_related("team").get(id=alert.id)
        )

        try:
            next_check_at_if_blocked = next_allowed_check_at(
                now,
                team_timezone=current_alert.team.timezone,
                schedule_restriction=current_alert.schedule_restriction,
            )
        except Exception as e:
            logger.exception(
                "Skipping tracing alert with invalid quiet-hours configuration",
                alert_id=str(current_alert.id),
                team_id=current_alert.team_id,
                error=str(e),
            )
            next_check_at_if_blocked = now

        if next_check_at_if_blocked > now:
            current_alert.next_check_at = next_check_at_if_blocked
            current_alert.save(update_fields=["next_check_at", "updated_at"])
            return "suppressed"

        state_before = current_alert.state
        produce_result = _dispatch_notification(
            outcome, current_alert, check_result, now, date_from=date_from, date_to=date_to
        )
        notification_failed = outcome.notification != NotificationAction.NONE and produce_result is None
        if produce_result is not None:
            flush_alert_internal_events(NOTIFICATION_FLUSH_TIMEOUT_SECONDS)
            notification_failed = not alert_internal_event_delivered(
                produce_result,
                team_id=current_alert.team_id,
                alert_id=str(current_alert.id),
                event_name=outcome.notification.value,
            )

        update_fields = apply_outcome(current_alert, outcome)
        current_alert.last_checked_at = now
        current_alert.updated_at = now
        next_check_at = advance_next_check_at(
            current_alert.next_check_at,
            current_alert.check_interval_minutes,
            now,
            shard_offset_seconds=compute_shard_offset_seconds(current_alert.id, current_alert.check_interval_minutes),
        )
        try:
            current_alert.next_check_at = next_allowed_check_at(
                next_check_at,
                team_timezone=current_alert.team.timezone,
                schedule_restriction=current_alert.schedule_restriction,
            )
        except Exception as e:
            logger.exception(
                "Ignoring invalid quiet-hours configuration while saving tracing alert",
                alert_id=str(current_alert.id),
                team_id=current_alert.team_id,
                error=str(e),
            )
            current_alert.next_check_at = next_check_at
        update_fields.extend(["last_checked_at", "next_check_at", "updated_at"])

        if (
            not notification_failed
            and outcome.notification != NotificationAction.NONE
            and outcome.update_last_notified_at
        ):
            current_alert.last_notified_at = now
            update_fields.append("last_notified_at")

        is_error = outcome.error_message is not None
        state_changed = state_before != outcome.new_state.value
        if state_changed or is_error:
            TracingAlertEvent.objects.create(
                alert=current_alert,
                result_count=check_result.result_count,
                threshold_breached=check_result.threshold_breached,
                state_before=state_before,
                state_after=outcome.new_state.value,
                error_message=outcome.error_message,
                query_duration_ms=check_result.query_duration_ms,
            )

        current_alert.save(update_fields=update_fields)

    if error_category is not None:
        return "errored"
    if outcome.notification == NotificationAction.FIRE:
        return "fired"
    if outcome.notification == NotificationAction.RESOLVE:
        return "resolved"
    return "unchanged"


def _produce_alert_internal_event(
    alert: TracingAlertConfiguration,
    event_name: str,
    properties: dict,
    now: datetime,
) -> ProduceResult | None:
    return produce_alert_internal_event(
        team_id=alert.team_id,
        event_name=event_name,
        properties=properties,
        timestamp=now,
    )


def _emit_alert_event(
    alert: TracingAlertConfiguration,
    event_name: str,
    check_result: CheckResult,
    now: datetime,
) -> ProduceResult | None:
    properties: dict = {
        "alert_id": str(alert.id),
        "alert_name": alert.name,
        "team_id": alert.team_id,
        "threshold_count": alert.threshold_count,
        "threshold_operator": alert.threshold_operator,
        "window_minutes": alert.window_minutes,
        "result_count": check_result.result_count,
        "filters": alert.filters,
        "service_names": alert.filters.get("serviceNames", []),
        "triggered_at": now.isoformat(),
    }
    return _produce_alert_internal_event(alert, event_name, properties, now)


def _base_failure_properties(
    alert: TracingAlertConfiguration,
    outcome: AlertCheckOutcome,
    now: datetime,
) -> dict:
    return {
        "alert_id": str(alert.id),
        "alert_name": alert.name,
        "team_id": alert.team_id,
        "consecutive_failures": outcome.consecutive_failures,
        "service_names": alert.filters.get("serviceNames", []),
        "triggered_at": now.isoformat(),
    }


def _emit_auto_disabled_event(
    alert: TracingAlertConfiguration, outcome: AlertCheckOutcome, now: datetime
) -> ProduceResult | None:
    properties = {**_base_failure_properties(alert, outcome, now), "last_error_message": outcome.error_message or ""}
    return _produce_alert_internal_event(alert, "$tracing_alert_auto_disabled", properties, now)


def _emit_alert_errored_event(
    alert: TracingAlertConfiguration, outcome: AlertCheckOutcome, now: datetime
) -> ProduceResult | None:
    properties = {**_base_failure_properties(alert, outcome, now), "error_message": outcome.error_message or ""}
    return _produce_alert_internal_event(alert, "$tracing_alert_errored", properties, now)


def _dispatch_notification(
    outcome: AlertCheckOutcome,
    alert: TracingAlertConfiguration,
    check_result: CheckResult,
    now: datetime,
    *,
    date_from: datetime,
    date_to: datetime,
) -> ProduceResult | None:
    action = outcome.notification
    if action == NotificationAction.NONE:
        return None

    log = logger.bind(alert_id=str(alert.id), alert_name=alert.name, team_id=alert.team_id)

    if action == NotificationAction.FIRE:
        result = _emit_alert_event(alert, "$tracing_alert_firing", check_result, now)
        log.info("Tracing alert fired", result_count=check_result.result_count, enqueued=result is not None)
    elif action == NotificationAction.RESOLVE:
        result = _emit_alert_event(alert, "$tracing_alert_resolved", check_result, now)
        log.info("Tracing alert resolved", enqueued=result is not None)
    elif action == NotificationAction.ERROR:
        result = _emit_alert_errored_event(alert, outcome, now)
        log.info(
            "Tracing alert entered errored state",
            consecutive_failures=outcome.consecutive_failures,
            enqueued=result is not None,
        )
    elif action == NotificationAction.BROKEN:
        result = _emit_auto_disabled_event(alert, outcome, now)
        log.warning(
            "Tracing alert broken after consecutive failures",
            consecutive_failures=outcome.consecutive_failures,
            enqueued=result is not None,
        )
    else:
        raise ValueError(f"Unhandled NotificationAction: {action!r}")

    return result
