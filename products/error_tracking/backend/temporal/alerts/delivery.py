"""Alert delivery planning: which alerts a lifecycle transition reaches.

Triggers gate thread openers only. A transition whose event satisfies one of an
alert's triggers opens a notification thread per destination; every other
lifecycle event is delivered as a reply to an existing thread, without a second
trigger or filter evaluation. Actual channel delivery (Slack threads) lands in a
follow-up; this module currently records the plan and returns the match count so
the workflow wiring can ship dark.
"""

import dataclasses

import structlog

from products.error_tracking.backend.models import (
    ErrorTrackingAlert,
    ErrorTrackingAlertDestination,
    ErrorTrackingAlertThread,
)
from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs

logger = structlog.get_logger(__name__)

# Which lifecycle event satisfies which alert trigger. Only these open a thread;
# every other lifecycle event is delivered as a reply to an existing thread.
OPENER_TRIGGERS = {
    "$error_tracking_issue_created": ErrorTrackingAlert.Trigger.ISSUE_CREATED,
    "$error_tracking_issue_reopened": ErrorTrackingAlert.Trigger.ISSUE_REOPENED,
    "$error_tracking_issue_spiking": ErrorTrackingAlert.Trigger.ISSUE_SPIKING,
    "$error_tracking_issue_assigned": ErrorTrackingAlert.Trigger.ISSUE_ASSIGNED,
}


@dataclasses.dataclass(frozen=True)
class PlannedDelivery:
    alert: ErrorTrackingAlert
    destinations: list[ErrorTrackingAlertDestination]
    is_opener: bool
    thread: ErrorTrackingAlertThread | None


def plan_alert_deliveries(inputs: AlertDeliveryWorkflowInputs) -> list[PlannedDelivery]:
    trigger = OPENER_TRIGGERS.get(inputs.event)
    alerts = list(ErrorTrackingAlert.objects.for_team(inputs.team_id).filter(enabled=True))
    destinations_by_alert: dict = {}
    for destination in ErrorTrackingAlertDestination.objects.for_team(inputs.team_id).filter(alert__in=alerts):
        destinations_by_alert.setdefault(destination.alert_id, []).append(destination)
    threads_by_alert = {
        thread.alert_id: thread
        for thread in ErrorTrackingAlertThread.objects.for_team(inputs.team_id).filter(issue_id=inputs.issue_id)
    }

    planned: list[PlannedDelivery] = []
    for alert in alerts:
        is_opener = trigger is not None and trigger in alert.triggers
        thread = threads_by_alert.get(alert.id)
        if thread is None and not is_opener:
            # Replies never open threads: an update with no rooted thread stays
            # unclaimed so a later opener can still start the conversation cleanly.
            continue
        planned.append(
            PlannedDelivery(
                alert=alert,
                destinations=destinations_by_alert.get(alert.id, []),
                is_opener=is_opener,
                thread=thread,
            )
        )
    return planned


def deliver_alert_notifications(inputs: AlertDeliveryWorkflowInputs) -> int:
    planned = plan_alert_deliveries(inputs)
    for delivery in planned:
        logger.info(
            "error_tracking_alert_delivery_planned",
            team_id=inputs.team_id,
            alert_id=str(delivery.alert.id),
            issue_id=inputs.issue_id,
            event=inputs.event,
            notification_id=inputs.notification_id,
            is_opener=delivery.is_opener,
            has_thread=delivery.thread is not None,
            destination_count=len(delivery.destinations),
        )
    # No channel delivery yet: the count reports matched alerts so the dark
    # wiring is observable end to end.
    return len(planned)
