"""Temporal activities for logs alerting."""

import time
import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta

from django.db import transaction
from django.db.models import F, Q

import structlog
import temporalio.activity

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.exceptions_capture import capture_exception

from products.logs.backend.alert_check_query import AlertCheckQuery
from products.logs.backend.alert_error_classifier import classify as classify_alert_error
from products.logs.backend.alert_state_machine import (
    AlertCheckOutcome,
    AlertState,
    CheckResult,
    NotificationAction,
    apply_outcome,
    evaluate_alert_check,
)
from products.logs.backend.alert_utils import advance_next_check_at
from products.logs.backend.logs_url_params import build_logs_url_params
from products.logs.backend.models import MAX_EVALUATION_PERIODS, LogsAlertCheck, LogsAlertConfiguration
from products.logs.backend.temporal.metrics import increment_checks_total, record_check_duration, record_scheduler_lag

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class CheckAlertsInput:
    pass


@dataclasses.dataclass(frozen=True)
class CheckAlertsOutput:
    alerts_checked: int
    alerts_fired: int
    alerts_resolved: int
    alerts_errored: int


@temporalio.activity.defn
async def check_alerts_activity(input: CheckAlertsInput) -> CheckAlertsOutput:
    """Find all due alerts and evaluate them sequentially."""
    result = await asyncio.to_thread(_check_alerts_sync)
    return result


def _check_alerts_sync() -> CheckAlertsOutput:
    """Synchronous alert checking — runs in a thread."""
    now = datetime.now(UTC)

    all_alerts = list(
        LogsAlertConfiguration.objects.filter(
            Q(enabled=True),
            Q(next_check_at__lte=now) | Q(next_check_at__isnull=True),
        )
        .select_related("team")
        .exclude(state=LogsAlertConfiguration.State.SNOOZED, snooze_until__gt=now)
        .exclude(state=LogsAlertConfiguration.State.BROKEN)
    )

    stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}

    # Sequential for now. TODO, stagger
    # or cap concurrency to avoid bursting all ClickHouse queries at :00 each minute.
    for alert in all_alerts:
        try:
            _evaluate_single_alert(alert, now, stats)
        except Exception:
            logger.exception(
                "Unexpected error evaluating alert",
                alert_id=str(alert.id),
                alert_name=alert.name,
                team_id=alert.team_id,
            )
            stats["errored"] += 1

    if stats["checked"] > 0:
        logger.info(
            "Alert check cycle complete",
            **stats,
        )

    return CheckAlertsOutput(
        alerts_checked=stats["checked"],
        alerts_fired=stats["fired"],
        alerts_resolved=stats["resolved"],
        alerts_errored=stats["errored"],
    )


def _evaluate_single_alert(
    alert: LogsAlertConfiguration,
    now: datetime,
    stats: dict[str, int],
) -> None:
    """Run the ClickHouse query, apply state machine, persist, and emit events for a single alert."""
    start_time = time.perf_counter()
    original_next_check_at = alert.next_check_at

    date_to = now
    date_from = now - timedelta(minutes=alert.window_minutes)

    check_result: CheckResult
    try:
        query_result = AlertCheckQuery(
            team=alert.team,
            alert=alert,
            date_from=date_from,
            date_to=date_to,
        ).execute()
        threshold_breached = (
            query_result.count > alert.threshold_count
            if alert.threshold_operator == "above"
            else query_result.count < alert.threshold_count
        )
        check_result = CheckResult(
            result_count=query_result.count,
            threshold_breached=threshold_breached,
            query_duration_ms=query_result.query_duration_ms,
        )
    except Exception as e:
        classified = classify_alert_error(e)
        capture_exception(e, {"alert_id": str(alert.id), "classification": classified.code})
        logger.warning(
            "Alert check query failed",
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
        )

    outcome = evaluate_alert_check(alert.to_snapshot(), check_result, now)

    # Attempt Kafka delivery BEFORE committing state transition.
    # If delivery fails and we needed to notify, keep old state so the
    # next tick retries the full transition (NOT_FIRING → FIRING again).
    notified = False
    notification_failed = False
    if outcome.notification == NotificationAction.FIRE:
        notified = _emit_alert_event(
            alert,
            "$logs_alert_firing",
            check_result,
            now,
            date_from=date_from,
            date_to=date_to,
        )
        notification_failed = not notified
        if notified:
            stats["fired"] += 1
        logger.info(
            "Alert fired",
            alert_id=str(alert.id),
            alert_name=alert.name,
            team_id=alert.team_id,
            result_count=check_result.result_count,
            notified=notified,
        )
    elif outcome.notification == NotificationAction.RESOLVE:
        notified = _emit_alert_event(
            alert,
            "$logs_alert_resolved",
            check_result,
            now,
            date_from=date_from,
            date_to=date_to,
        )
        notification_failed = not notified
        if notified:
            stats["resolved"] += 1
        logger.info(
            "Alert resolved",
            alert_id=str(alert.id),
            alert_name=alert.name,
            team_id=alert.team_id,
            notified=notified,
        )

    # If the notification delivery failed, don't commit the state transition
    # so the next tick will re-evaluate and retry the notification.
    if notification_failed:
        committed_outcome = dataclasses.replace(outcome, new_state=AlertState(alert.state))
    else:
        committed_outcome = outcome
    committed_state = committed_outcome.new_state

    state_before = alert.state
    with transaction.atomic():
        LogsAlertCheck.objects.create(
            alert=alert,
            result_count=check_result.result_count,
            threshold_breached=check_result.threshold_breached,
            state_before=state_before,
            state_after=committed_state.value,
            error_message=outcome.error_message,
            query_duration_ms=check_result.query_duration_ms,
        )

        # All state/consecutive_failures writes go through apply_outcome —
        # single source of truth, enforced by the semgrep rule.
        update_fields = apply_outcome(alert, committed_outcome)
        alert.last_checked_at = now
        alert.next_check_at = advance_next_check_at(alert.next_check_at, alert.check_interval_minutes, now)
        update_fields.extend(["last_checked_at", "next_check_at", "updated_at"])

        if notified and outcome.update_last_notified_at:
            alert.last_notified_at = now
            update_fields.append("last_notified_at")

        alert.save(update_fields=update_fields)

    # Per-alert cap on non-event rows, enforced inline so the table stays bounded between
    # daily cleanup runs. Errored rows and state transitions survive (event-retention task).
    # Best-effort and deliberately outside the transaction above: a missed check would skew
    # the alert's N-of-M window, a missed prune just leaves one extra row that the next
    # tick's prune will mop up. Prefer the eventual-consistency failure mode.
    # Upper-bound the slice so a one-time backlog (e.g. first deploy, or a disabled alert
    # that accumulated rows) doesn't materialize thousands of IDs in one tick — subsequent
    # ticks finish the job.
    try:
        prunable_ids = list(
            LogsAlertCheck.objects.filter(
                alert=alert,
                error_message__isnull=True,
                state_before=F("state_after"),
            )
            .order_by("-created_at")
            .values_list("id", flat=True)[MAX_EVALUATION_PERIODS : MAX_EVALUATION_PERIODS + 500]
        )
        if prunable_ids:
            LogsAlertCheck.objects.filter(id__in=prunable_ids).delete()
    except Exception:
        logger.exception("Failed to prune non-event check rows", alert_id=str(alert.id))

    transitioned_to_broken = committed_state == AlertState.BROKEN and state_before != AlertState.BROKEN.value
    if transitioned_to_broken:
        logger.warning(
            "Alert broken after consecutive failures",
            alert_id=str(alert.id),
            alert_name=alert.name,
            team_id=alert.team_id,
            consecutive_failures=outcome.consecutive_failures,
        )
        _emit_auto_disabled_event(alert, outcome, now)

    stats["checked"] += 1

    if outcome.error_message:
        stats["errored"] += 1

    # Per-alert metrics — must never break alerting
    try:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        record_check_duration(elapsed_ms)
        if original_next_check_at is not None:
            lag_ms = int((now - original_next_check_at).total_seconds() * 1000)
            if lag_ms > 0:
                record_scheduler_lag(lag_ms)
        if outcome.error_message:
            increment_checks_total("errored")
        elif notification_failed:
            increment_checks_total("errored")
        elif outcome.notification == NotificationAction.FIRE:
            increment_checks_total("fired")
        elif outcome.notification == NotificationAction.RESOLVE:
            increment_checks_total("resolved")
        else:
            increment_checks_total("ok")
    except Exception:
        logger.exception("Failed to record alert check metrics", alert_id=str(alert.id))


def _produce_alert_internal_event(
    alert: LogsAlertConfiguration,
    event_name: str,
    properties: dict,
    now: datetime,
) -> bool:
    try:
        produce_internal_event(
            team_id=alert.team_id,
            event=InternalEventEvent(
                event=event_name,
                distinct_id=f"team_{alert.team_id}",
                properties=properties,
                timestamp=now.isoformat(),
            ),
        )
        return True
    except Exception as e:
        capture_exception(e, {"alert_id": str(alert.id), "event": event_name})
        return False


def _emit_alert_event(
    alert: LogsAlertConfiguration,
    event_name: str,
    check_result: CheckResult,
    now: datetime,
    *,
    date_from: datetime,
    date_to: datetime,
) -> bool:
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
        "severity_levels": alert.filters.get("severityLevels", []),
        "logs_url_params": build_logs_url_params(alert.filters, date_from=date_from, date_to=date_to),
        "triggered_at": now.isoformat(),
    }
    return _produce_alert_internal_event(alert, event_name, properties, now)


def _emit_auto_disabled_event(
    alert: LogsAlertConfiguration,
    outcome: AlertCheckOutcome,
    now: datetime,
) -> None:
    properties: dict = {
        "alert_id": str(alert.id),
        "alert_name": alert.name,
        "team_id": alert.team_id,
        "consecutive_failures": outcome.consecutive_failures,
        "last_error_message": outcome.error_message or "",
        "service_names": alert.filters.get("serviceNames", []),
        "severity_levels": alert.filters.get("severityLevels", []),
        "triggered_at": now.isoformat(),
    }
    _produce_alert_internal_event(alert, "$logs_alert_auto_disabled", properties, now)
