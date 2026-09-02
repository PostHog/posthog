"""Temporal activities for metrics alerting.

Two activities: discover due alerts (a cheap Postgres scan), then check each alert
(evaluate the metric query, run the shared state machine, dispatch the notification,
persist). One `check_metrics_alert_activity` runs per due alert, fanned out by the
workflow across workers.

Delivery is transactional with lifecycle state: a notification is produced to Kafka
and flushed BEFORE the new state is saved; if the broker never acks, the state rolls
back so the next cycle re-evaluates and retries the notification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from django.db import transaction

import structlog
import temporalio.activity

from posthog.kafka_client.client import ProduceResult
from posthog.models.team import Team

from products.alerts.backend.destinations import (
    alert_internal_event_delivered,
    flush_alert_internal_events,
    produce_alert_internal_event,
)
from products.alerts.backend.scheduling import advance_next_check_at, compute_shard_offset_seconds
from products.metrics.backend.alert_evaluation import evaluate_metric_alert
from products.metrics.backend.alert_state_machine import (
    AlertState,
    CheckResult,
    ControlPlaneOutcome,
    NotificationAction,
    apply_outcome,
    evaluate_alert_check,
)
from products.metrics.backend.models import MetricsAlertConfiguration, MetricsAlertEvent
from products.metrics.backend.temporal.constants import NOTIFICATION_FLUSH_TIMEOUT_SECONDS

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DiscoverMetricsAlertsInput:
    pass


@dataclass(frozen=True)
class DiscoveredAlert:
    alert_id: str
    team_id: int


@dataclass(frozen=True)
class DiscoverMetricsAlertsOutput:
    alerts: list[DiscoveredAlert]


@dataclass(frozen=True)
class CheckMetricsAlertInput:
    alert_id: str
    team_id: int


@dataclass(frozen=True)
class CheckMetricsAlertOutput:
    alert_id: str
    state_before: str
    state_after: str
    notification: str
    value: float | None


def _due_alerts_qs(now: datetime) -> Any:
    """Enabled, non-broken, non-snoozed alerts whose check is due (or never scheduled)."""
    base = (
        MetricsAlertConfiguration.objects.filter(enabled=True)
        .exclude(state=MetricsAlertConfiguration.State.BROKEN)
        .exclude(
            state=MetricsAlertConfiguration.State.SNOOZED,
            snooze_until__gt=now,
        )
    )
    due = base.filter(next_check_at__lte=now)
    never_scheduled = base.filter(next_check_at__isnull=True)
    return due | never_scheduled


def _discover() -> DiscoverMetricsAlertsOutput:
    now = datetime.now(UTC)
    rows = _due_alerts_qs(now).values("id", "team_id")
    alerts = [DiscoveredAlert(alert_id=str(r["id"]), team_id=r["team_id"]) for r in rows]
    logger.info("Discovered due metrics alerts", count=len(alerts))
    return DiscoverMetricsAlertsOutput(alerts=alerts)


@temporalio.activity.defn
async def discover_metrics_alerts_activity(input: DiscoverMetricsAlertsInput) -> DiscoverMetricsAlertsOutput:
    # Deferred: keep Django off the Temporal workflow-sandbox import path (workflow.py
    # imports this module to reference the activity callables).
    from posthog.sync import database_sync_to_async_pool  # noqa: PLC0415

    return await database_sync_to_async_pool(_discover)()


def _emit_notification(
    alert: MetricsAlertConfiguration,
    action: NotificationAction,
    check_result: CheckResult,
    now: datetime,
    consecutive_failures: int,
    error_message: str | None,
) -> ProduceResult | None:
    base = {
        "alert_id": str(alert.id),
        "alert_name": alert.name,
        "team_id": alert.team_id,
        "metric_name": alert.metric_name,
        "triggered_at": now.isoformat(),
    }
    if action == NotificationAction.FIRE:
        props = {
            **base,
            "value": check_result.value,
            "threshold_value": alert.threshold_value,
            "threshold_operator": alert.threshold_operator,
            "window_minutes": alert.window_minutes,
            "labels": check_result.labels,
        }
        return produce_alert_internal_event(
            team_id=alert.team_id, event_name="$metrics_alert_firing", properties=props, timestamp=now
        )
    if action == NotificationAction.RESOLVE:
        props = {
            **base,
            "value": check_result.value,
            "threshold_value": alert.threshold_value,
            "threshold_operator": alert.threshold_operator,
            "window_minutes": alert.window_minutes,
        }
        return produce_alert_internal_event(
            team_id=alert.team_id, event_name="$metrics_alert_resolved", properties=props, timestamp=now
        )
    if action == NotificationAction.ERROR:
        props = {**base, "consecutive_failures": consecutive_failures, "error_message": error_message or ""}
        return produce_alert_internal_event(
            team_id=alert.team_id, event_name="$metrics_alert_errored", properties=props, timestamp=now
        )
    if action == NotificationAction.BROKEN:
        props = {
            **base,
            "consecutive_failures": consecutive_failures,
            "last_error_message": error_message or "",
        }
        return produce_alert_internal_event(
            team_id=alert.team_id, event_name="$metrics_alert_auto_disabled", properties=props, timestamp=now
        )
    return None


@temporalio.activity.defn
async def check_metrics_alert_activity(input: CheckMetricsAlertInput) -> CheckMetricsAlertOutput:
    from posthog.sync import database_sync_to_async_pool  # noqa: PLC0415

    return await database_sync_to_async_pool(_check_metrics_alert_sync)(input)


def _check_metrics_alert_sync(input: CheckMetricsAlertInput) -> CheckMetricsAlertOutput:
    now = datetime.now(UTC)
    try:
        alert = MetricsAlertConfiguration.objects.select_related("team").get(id=input.alert_id, team_id=input.team_id)
    except MetricsAlertConfiguration.DoesNotExist:
        logger.warning("Metrics alert vanished before check", alert_id=input.alert_id)
        return CheckMetricsAlertOutput(
            alert_id=input.alert_id, state_before="", state_after="", notification="none", value=None
        )

    team: Team = alert.team
    state_before = alert.state

    # 1. Domain evaluation — decide breached/clear/errored from metric data.
    recent_breaches = alert.get_recent_breaches()
    check_result = evaluate_metric_alert(alert, team, date_to=alert.next_check_at or now)

    # 2. Lifecycle decision via the shared state machine.
    outcome = evaluate_alert_check(alert.to_snapshot(recent_events_breached=recent_breaches), check_result, now)

    # 3. Dispatch the notification (if any) and flush before persisting state.
    notification_failed = False
    if outcome.notification != NotificationAction.NONE:
        produce_result = _emit_notification(
            alert,
            outcome.notification,
            check_result,
            now,
            consecutive_failures=outcome.consecutive_failures,
            error_message=outcome.error_message,
        )
        if produce_result is None:
            notification_failed = True
        else:
            flush_alert_internal_events(NOTIFICATION_FLUSH_TIMEOUT_SECONDS)
            notification_failed = not alert_internal_event_delivered(
                produce_result,
                team_id=alert.team_id,
                alert_id=str(alert.id),
                event_name=outcome.notification.value,
            )

    # Roll the state back if delivery failed so the next cycle retries the notification.
    committed_outcome = outcome
    if notification_failed:
        committed_outcome = ControlPlaneOutcome(
            new_state=AlertState(state_before),
            consecutive_failures=min(alert.consecutive_failures, outcome.consecutive_failures),
        )

    # 4. Persist state + history.
    with transaction.atomic():
        update_fields = apply_outcome(alert, committed_outcome)
        alert.last_checked_at = now
        next_check_at = advance_next_check_at(
            alert.next_check_at,
            alert.check_interval_minutes,
            now,
            shard_offset_seconds=compute_shard_offset_seconds(alert.id, alert.check_interval_minutes),
        )
        alert.next_check_at = next_check_at
        update_fields.extend(["last_checked_at", "next_check_at", "updated_at"])

        if (
            not notification_failed
            and outcome.notification != NotificationAction.NONE
            and outcome.update_last_notified_at
        ):
            alert.last_notified_at = now
            update_fields.append("last_notified_at")

        # Record every evaluated check. N-of-M reads the window back from these
        # rows via get_recent_breaches, so skipping a non-state-changing breach
        # would silently drop the first N-1 breaches of the window.
        MetricsAlertEvent.objects.create(
            alert=alert,
            kind=MetricsAlertEvent.Kind.CHECK,
            value=check_result.value,
            threshold_breached=check_result.threshold_breached,
            labels=check_result.labels,
            state_before=state_before,
            state_after=committed_outcome.new_state.value,
            error_message=check_result.error_message,
            query_duration_ms=check_result.query_duration_ms,
        )
        alert.save(update_fields=update_fields)

    logger.info(
        "Metrics alert checked",
        alert_id=str(alert.id),
        state_before=state_before,
        state_after=committed_outcome.new_state.value,
        notification=outcome.notification.value,
        notification_failed=notification_failed,
        value=check_result.value,
    )
    return CheckMetricsAlertOutput(
        alert_id=str(alert.id),
        state_before=state_before,
        state_after=committed_outcome.new_state.value,
        notification=outcome.notification.value,
        value=check_result.value,
    )
