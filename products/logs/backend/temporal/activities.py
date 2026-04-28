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
from posthog.sync import database_sync_to_async_pool

from products.logs.backend.alert_check_query import (
    AlertCheckQuery,
    BucketedCount,
    fetch_live_logs_checkpoint,
    resolve_alert_date_to,
)
from products.logs.backend.alert_error_classifier import (
    AlertErrorCode,
    classify as classify_alert_error,
)
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
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent
from products.logs.backend.temporal.constants import MAX_CONCURRENT_ALERT_EVALS
from products.logs.backend.temporal.metrics import (
    increment_check_errors,
    increment_checkpoint_unavailable,
    increment_checks_total,
    increment_notification_failures,
    increment_state_transition,
    record_alerts_active,
    record_check_duration,
    record_checkpoint_lag,
    record_scheduler_lag,
)

logger = structlog.get_logger(__name__)


def _derive_breaches(
    buckets: list[BucketedCount],
    threshold_count: int,
    threshold_operator: str,
    evaluation_periods: int,
) -> tuple[bool, ...]:
    """Map ASC-ordered bucketed CH counts to a newest-first breach tuple of length M.

    CH's `GROUP BY` only emits buckets that have data. The state machine needs M
    data points regardless of how sparse the underlying log volume is — so we
    pad the result to `evaluation_periods` with the implicit count=0 outcome:
    `False` for `above` (0 < threshold), `True` for `below` (0 < threshold given
    the model's min_value=1 validator).

    Without this pad, a `below` alert on a truly silent service would never
    fire — CH returns no buckets, the breach tuple is empty, and the N-of-M
    evaluator never sees the implicit "count is below threshold" signal.
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


@temporalio.activity.defn
async def check_alerts_activity(input: CheckAlertsInput) -> CheckAlertsOutput:
    """Find all due alerts and evaluate them with bounded concurrency."""
    now, all_alerts, checkpoint = await database_sync_to_async_pool(_load_alerts_and_checkpoint)()

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_ALERT_EVALS)
    eval_async = database_sync_to_async_pool(_evaluate_single_alert)

    async def _bounded_eval(alert: LogsAlertConfiguration) -> dict[str, int]:
        async with semaphore:
            local_stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
            try:
                await eval_async(alert, now, local_stats, checkpoint=checkpoint)
            except Exception:
                logger.exception(
                    "Unexpected error evaluating alert",
                    alert_id=str(alert.id),
                    alert_name=alert.name,
                    team_id=alert.team_id,
                )
                local_stats["errored"] += 1
            return local_stats

    tasks: list[asyncio.Task[dict[str, int]]] = []
    async with asyncio.TaskGroup() as tg:
        for alert in all_alerts:
            tasks.append(tg.create_task(_bounded_eval(alert)))

    aggregated = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
    for task in tasks:
        for k, v in task.result().items():
            aggregated[k] += v

    if aggregated["checked"] > 0:
        logger.info("Alert check cycle complete", **aggregated)

    return CheckAlertsOutput(
        alerts_checked=aggregated["checked"],
        alerts_fired=aggregated["fired"],
        alerts_resolved=aggregated["resolved"],
        alerts_errored=aggregated["errored"],
    )


def _load_alerts_and_checkpoint() -> tuple[datetime, list[LogsAlertConfiguration], datetime | None]:
    """Sync setup: pin `now`, load due alerts, fetch ingestion checkpoint, emit cycle metrics."""
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

    try:
        record_alerts_active(len(all_alerts))
    except Exception:
        logger.exception("Failed to record alerts_active gauge")

    checkpoint: datetime | None = None
    if all_alerts:
        try:
            checkpoint = fetch_live_logs_checkpoint(all_alerts[0].team)
        except Exception:
            logger.exception("Failed to fetch logs ingestion checkpoint; falling back to wall-clock")

    try:
        if checkpoint is None:
            increment_checkpoint_unavailable()
        else:
            record_checkpoint_lag(now, checkpoint)
    except Exception:
        logger.exception("Failed to record checkpoint metric")

    return now, all_alerts, checkpoint


def _check_alerts_sync() -> CheckAlertsOutput:
    """Synchronous variant kept for unit tests. Production runs through
    `check_alerts_activity` (async + bounded concurrency)."""
    now, all_alerts, checkpoint = _load_alerts_and_checkpoint()

    stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
    for alert in all_alerts:
        try:
            _evaluate_single_alert(alert, now, stats, checkpoint=checkpoint)
        except Exception:
            logger.exception(
                "Unexpected error evaluating alert",
                alert_id=str(alert.id),
                alert_name=alert.name,
                team_id=alert.team_id,
            )
            stats["errored"] += 1

    if stats["checked"] > 0:
        logger.info("Alert check cycle complete", **stats)

    return CheckAlertsOutput(
        alerts_checked=stats["checked"],
        alerts_fired=stats["fired"],
        alerts_resolved=stats["resolved"],
        alerts_errored=stats["errored"],
    )


def _dispatch_notification(
    outcome: AlertCheckOutcome,
    alert: LogsAlertConfiguration,
    check_result: CheckResult,
    now: datetime,
    stats: dict[str, int],
    *,
    date_from: datetime,
    date_to: datetime,
) -> bool:
    """Emit the notification for this outcome. Returns True if delivery failed."""
    action = outcome.notification
    if action == NotificationAction.NONE:
        return False

    log = logger.bind(alert_id=str(alert.id), alert_name=alert.name, team_id=alert.team_id)

    if action == NotificationAction.FIRE:
        notified = _emit_alert_event(
            alert, "$logs_alert_firing", check_result, now, date_from=date_from, date_to=date_to
        )
        if notified:
            stats["fired"] += 1
        log.info("Alert fired", result_count=check_result.result_count, notified=notified)
    elif action == NotificationAction.RESOLVE:
        notified = _emit_alert_event(
            alert, "$logs_alert_resolved", check_result, now, date_from=date_from, date_to=date_to
        )
        if notified:
            stats["resolved"] += 1
        log.info("Alert resolved", notified=notified)
    elif action == NotificationAction.ERROR:
        notified = _emit_alert_errored_event(alert, outcome, now)
        log.info("Alert entered errored state", consecutive_failures=outcome.consecutive_failures, notified=notified)
    elif action == NotificationAction.BROKEN:
        notified = _emit_auto_disabled_event(alert, outcome, now)
        log.warning(
            "Alert broken after consecutive failures",
            consecutive_failures=outcome.consecutive_failures,
            notified=notified,
        )
    else:
        raise ValueError(f"Unhandled NotificationAction: {action!r}")

    return not notified


def _evaluate_single_alert(
    alert: LogsAlertConfiguration,
    now: datetime,
    stats: dict[str, int],
    *,
    checkpoint: datetime | None = None,
) -> None:
    """Run the ClickHouse query, apply state machine, persist, and emit events for a single alert.

    Stateless eval: a single bucketed CH query returns the last M counts; the
    N-of-M evaluator decides from those buckets directly. Anchored on
    `next_check_at` so two evals at different actual eval times produce the
    same query.
    """
    start_time = time.perf_counter()
    original_next_check_at = alert.next_check_at

    # First-run alerts (`next_check_at` still null after enable) anchor on `now`;
    # from the second eval onward, `next_check_at` is set and idempotence holds.
    nca = alert.next_check_at if alert.next_check_at is not None else now
    date_to = resolve_alert_date_to(nca, checkpoint)
    # Each bucket represents one historical "what the alert query would have
    # returned" — window_minutes of data. M buckets cover M * window_minutes total.
    date_from = date_to - timedelta(minutes=alert.window_minutes * alert.evaluation_periods)

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
        ).execute_bucketed(interval_minutes=alert.window_minutes, limit=alert.evaluation_periods)
        query_duration_ms = int((time.perf_counter() - query_start) * 1000)

        # execute_bucketed returns ASC (oldest first); state machine wants newest first.
        # Buckets that are entirely empty are absent from the result, so a sparse window
        # naturally produces a shorter breaches tuple — same behavior as today's
        # get_recent_breaches when fewer than M CHECK rows exist.
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
            is_transient_error=classified.is_transient,
        )

    outcome = evaluate_alert_check(alert.to_snapshot(recent_events_breached=recent_breaches), check_result, now)

    # Attempt Kafka delivery BEFORE committing state transition.
    # If delivery fails and we needed to notify, keep old state so the
    # next tick retries the full transition (NOT_FIRING → FIRING again).
    notification_failed = _dispatch_notification(
        outcome, alert, check_result, now, stats, date_from=date_from, date_to=date_to
    )
    # If the notification delivery failed, don't commit the state transition
    # so the next tick will re-evaluate and retry the notification.
    if notification_failed:
        committed_outcome = dataclasses.replace(outcome, new_state=AlertState(alert.state))
    else:
        committed_outcome = outcome
    committed_state = committed_outcome.new_state

    state_before = alert.state
    state_changed = state_before != committed_state.value
    is_error = outcome.error_message is not None
    with transaction.atomic():
        # Stateless eval: write a CHECK row only on state transition or eval error.
        # Steady-state same-state evals don't write — the N-of-M evaluator gets its
        # window from the bucketed CH query, not from PG.
        if state_changed or is_error:
            LogsAlertEvent.objects.create(
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

        if (
            not notification_failed
            and outcome.notification != NotificationAction.NONE
            and outcome.update_last_notified_at
        ):
            alert.last_notified_at = now
            update_fields.append("last_notified_at")

        alert.save(update_fields=update_fields)

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

        if error_category is not None:
            increment_check_errors(error_category)

        if notification_failed:
            increment_notification_failures(outcome.notification)

        state_before_enum = AlertState(state_before)
        if committed_state != state_before_enum:
            increment_state_transition(state_before_enum, committed_state)
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


def _base_failure_properties(
    alert: LogsAlertConfiguration,
    outcome: AlertCheckOutcome,
    now: datetime,
) -> dict:
    return {
        "alert_id": str(alert.id),
        "alert_name": alert.name,
        "team_id": alert.team_id,
        "consecutive_failures": outcome.consecutive_failures,
        "service_names": alert.filters.get("serviceNames", []),
        "severity_levels": alert.filters.get("severityLevels", []),
        "triggered_at": now.isoformat(),
    }


def _emit_auto_disabled_event(
    alert: LogsAlertConfiguration,
    outcome: AlertCheckOutcome,
    now: datetime,
) -> bool:
    properties = {
        **_base_failure_properties(alert, outcome, now),
        "last_error_message": outcome.error_message or "",
    }
    return _produce_alert_internal_event(alert, "$logs_alert_auto_disabled", properties, now)


def _emit_alert_errored_event(
    alert: LogsAlertConfiguration,
    outcome: AlertCheckOutcome,
    now: datetime,
) -> bool:
    properties = {
        **_base_failure_properties(alert, outcome, now),
        "error_message": outcome.error_message or "",
    }
    return _produce_alert_internal_event(alert, "$logs_alert_errored", properties, now)
