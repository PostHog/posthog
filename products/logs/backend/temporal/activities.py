"""Temporal activities for logs alerting."""

import time
import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta

from django.db import transaction
from django.db.models import Q

import structlog
import temporalio.activity

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.exceptions_capture import capture_exception

from products.logs.backend.alert_check_query import AlertCheckQuery
from products.logs.backend.alert_state_machine import (
    AlertCheckOutcome,
    AlertSnapshot,
    AlertState,
    CheckResult,
    NotificationAction,
    evaluate_alert_check,
)
from products.logs.backend.alert_utils import advance_next_check_at
from products.logs.backend.logs_url_params import build_logs_url_params
from products.logs.backend.models import LogsAlertCheck, LogsAlertConfiguration
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
        logger.warning(
            "Alert check query failed",
            alert_id=str(alert.id),
            alert_name=alert.name,
            team_id=alert.team_id,
            error=str(e),
        )
        check_result = CheckResult(
            result_count=None,
            threshold_breached=False,
            error_message=str(e),
        )

    snapshot = AlertSnapshot(
        state=AlertState(alert.state),
        evaluation_periods=alert.evaluation_periods,
        datapoints_to_alarm=alert.datapoints_to_alarm,
        cooldown_minutes=alert.cooldown_minutes,
        last_notified_at=alert.last_notified_at,
        snooze_until=alert.snooze_until,
        consecutive_failures=alert.consecutive_failures,
        recent_checks_breached=alert.get_recent_breaches(),
    )

    outcome = evaluate_alert_check(snapshot, check_result, now)

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
    committed_state = AlertState(alert.state) if notification_failed else outcome.new_state

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

        alert.state = committed_state.value
        alert.consecutive_failures = outcome.consecutive_failures
        alert.last_checked_at = now
        alert.next_check_at = advance_next_check_at(alert.next_check_at, alert.check_interval_minutes, now)

        update_fields = ["state", "consecutive_failures", "last_checked_at", "next_check_at", "updated_at"]

        if notified and outcome.update_last_notified_at:
            alert.last_notified_at = now
            update_fields.append("last_notified_at")

        alert.save(update_fields=update_fields)

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
