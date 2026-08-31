"""Alert delivery: one Slack thread per (alert, issue, destination).

Triggers gate thread openers only. A transition whose event satisfies one of an
alert's triggers opens a notification thread per destination: a root Slack
message whose `ts` is stored on the thread row. Every other lifecycle event is
delivered as a reply into that thread, without a second trigger evaluation, and
status transitions also edit the root in place. Delivered notification ids are
recorded on the thread row so workflow retries never double-post. The alert's
stored filters are evaluated by the follow-up filter-evaluation layer before
openers actually send; until then delivery is trigger-only.
"""

import dataclasses

from django.db import IntegrityError

import structlog
from slack_sdk import WebClient

from posthog.models.integration import Integration, SlackIntegration

from products.error_tracking.backend.models import (
    ErrorTrackingAlert,
    ErrorTrackingAlertDestination,
    ErrorTrackingAlertThread,
)
from products.error_tracking.backend.temporal.alerts.messages import (
    DEFAULT_HEADLINE,
    build_reply_text,
    build_root_edit,
    build_root_message,
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

# Status transitions also update the root message in place. The headline stays:
# it is the thread's identity.
ROOT_EDIT_EVENTS = {
    "$error_tracking_issue_resolved",
    "$error_tracking_issue_suppressed",
    "$error_tracking_issue_reopened",
}

DELIVERED_NOTIFICATION_IDS_CAP = 200


class AlertDeliveryError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class PlannedDelivery:
    """One (alert, destination) conversation this transition reaches."""

    alert: ErrorTrackingAlert
    destination: ErrorTrackingAlertDestination
    is_opener: bool
    thread: ErrorTrackingAlertThread | None


def plan_alert_deliveries(inputs: AlertDeliveryWorkflowInputs) -> list[PlannedDelivery]:
    trigger = OPENER_TRIGGERS.get(inputs.event)
    alerts = list(ErrorTrackingAlert.objects.for_team(inputs.team_id).filter(enabled=True))
    destinations_by_alert: dict = {}
    for destination in (
        ErrorTrackingAlertDestination.objects.for_team(inputs.team_id)
        .filter(alert__in=alerts)
        .select_related("integration")
    ):
        destinations_by_alert.setdefault(destination.alert_id, []).append(destination)
    # Threads are unique per (alert, issue, destination): a multi-destination alert
    # holds one independent conversation per destination.
    threads_by_destination = {
        thread.destination_id: thread
        for thread in ErrorTrackingAlertThread.objects.for_team(inputs.team_id).filter(issue_id=inputs.issue_id)
    }

    planned: list[PlannedDelivery] = []
    for alert in alerts:
        trigger_matched = trigger is not None and trigger in alert.triggers
        for destination in destinations_by_alert.get(alert.id, []):
            thread = threads_by_destination.get(destination.id)
            if thread is None and not trigger_matched:
                # Replies never open threads: an update with no rooted thread stays
                # unclaimed so a later opener can still start the conversation cleanly.
                continue
            # Only the first matching transition opens; once a destination has a
            # thread, every later transition is a reply into it, even a repeated
            # opener event (e.g. spiking again, or reopen after resolve).
            is_opener = trigger_matched and thread is None
            planned.append(PlannedDelivery(alert=alert, destination=destination, is_opener=is_opener, thread=thread))
    return planned


def deliver_alert_notifications(inputs: AlertDeliveryWorkflowInputs) -> int:
    planned = plan_alert_deliveries(inputs)
    delivered = 0
    failures = 0
    for delivery in planned:
        try:
            if _deliver_one(delivery, inputs):
                delivered += 1
        except Exception:
            # Give every destination a chance before surfacing the failure to
            # Temporal; the per-notification claim makes the retry safe for the
            # deliveries that already went out.
            logger.exception(
                "error_tracking_alert_delivery_failed",
                team_id=inputs.team_id,
                alert_id=str(delivery.alert.id),
                destination_id=str(delivery.destination.id),
                issue_id=inputs.issue_id,
                lifecycle_event=inputs.event,
                notification_id=inputs.notification_id,
            )
            failures += 1
    if failures:
        raise AlertDeliveryError(f"{failures} of {len(planned)} alert deliveries failed")
    return delivered


def _deliver_one(delivery: PlannedDelivery, inputs: AlertDeliveryWorkflowInputs) -> bool:
    thread = delivery.thread
    if thread is None:
        # Planner guarantee: only openers arrive without a thread. The unique
        # constraint is the concurrency primitive; the insert-race loser reuses
        # the winner's row.
        try:
            thread, _ = ErrorTrackingAlertThread.objects.for_team(delivery.alert.team_id, canonical=True).get_or_create(
                alert=delivery.alert,
                issue_id=inputs.issue_id,
                destination=delivery.destination,
                defaults={"team_id": delivery.alert.team_id},
            )
        except IntegrityError:
            # The issue row is gone (merged away or deleted): nothing to alert on.
            return False

    if inputs.notification_id in (thread.delivered_notification_ids or []):
        return False

    client = _slack_client(delivery.destination)
    if client is None:
        # A revoked or repointed integration is a configuration gap, not a
        # transient failure: retries cannot fix it, so skip without raising.
        # Per-destination failure records land in the follow-up outcomes layer.
        logger.warning(
            "error_tracking_alert_destination_unusable",
            team_id=delivery.alert.team_id,
            alert_id=str(delivery.alert.id),
            destination_id=str(delivery.destination.id),
        )
        return False

    if not thread.external_ref.get("ts"):
        if not delivery.is_opener:
            # The row exists but was never rooted (a previous root post failed):
            # leave this notification unclaimed so a later opener still roots.
            return False
        channel = delivery.destination.config.get("channel")
        if not channel:
            return False
        message = build_root_message(inputs)
        response = client.chat_postMessage(channel=channel, blocks=message["blocks"], text=message["text"])
        # A crash between the post above and the save below re-posts the root on
        # retry: at-least-once delivery, never a lost notification. A concurrent
        # opener for a different notification can race into the same window; a
        # claim-before-send record closes both gaps before any broad rollout.
        thread.external_ref = {"channel": response["channel"], "ts": response["ts"]}
        thread.root_headline = message["headline"]
    else:
        reply = build_reply_text(inputs)
        if reply is None:
            return False
        # Replies stay in the thread's own channel: a provider thread cannot move,
        # so a repointed destination only applies to newly opened threads.
        client.chat_postMessage(
            channel=thread.external_ref["channel"],
            thread_ts=thread.external_ref["ts"],
            text=reply,
        )
        _maybe_edit_root(client, thread, inputs)

    thread.delivered_notification_ids = [*(thread.delivered_notification_ids or []), inputs.notification_id][
        -DELIVERED_NOTIFICATION_IDS_CAP:
    ]
    thread.save(update_fields=["external_ref", "root_headline", "delivered_notification_ids", "updated_at"])
    return True


def _maybe_edit_root(client: WebClient, thread: ErrorTrackingAlertThread, inputs: AlertDeliveryWorkflowInputs) -> None:
    if inputs.event not in ROOT_EDIT_EVENTS:
        return
    message = build_root_edit(inputs, headline=thread.root_headline or DEFAULT_HEADLINE)
    try:
        client.chat_update(
            channel=thread.external_ref["channel"],
            ts=thread.external_ref["ts"],
            blocks=message["blocks"],
            text=message["text"],
        )
    except Exception:
        # The threaded reply already delivered the update; a failed root edit only
        # leaves a stale status line behind, so it never fails the delivery.
        logger.exception(
            "error_tracking_alert_root_edit_failed",
            thread_id=str(thread.id),
            lifecycle_event=inputs.event,
        )


def _slack_client(destination: ErrorTrackingAlertDestination) -> WebClient | None:
    integration = destination.integration
    if integration is None or integration.kind != Integration.IntegrationKind.SLACK:
        return None
    return SlackIntegration(integration).client
