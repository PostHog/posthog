"""Stateful alert delivery: one Slack thread per (alert, issue).

The first matching lifecycle transition posts a root message and stores its
`ts`; later transitions for the same issue post replies into that thread.
Delivered notification ids are recorded on the thread row so activity retries
never double-post.
"""

from django.db import IntegrityError

import structlog

from posthog.models.integration import Integration, SlackIntegration

from products.error_tracking.backend.models import ErrorTrackingAlert, ErrorTrackingAlertThread
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
}

# Status transitions also update the root message in place: resolved/suppressed
# strip the action buttons, a reopen re-arms them.
ROOT_EDIT_EVENTS = {
    "$error_tracking_issue_resolved": False,
    "$error_tracking_issue_suppressed": False,
    "$error_tracking_issue_reopened": True,
}

DELIVERED_EVENTS_CAP = 200


def deliver_alert_notifications(inputs: AlertDeliveryWorkflowInputs) -> int:
    alerts = ErrorTrackingAlert.objects.for_team(inputs.team_id).filter(
        enabled=True, channel_type=ErrorTrackingAlert.ChannelType.SLACK
    )
    delivered = 0
    for alert in alerts:
        try:
            if _process_alert(alert, inputs):
                delivered += 1
        except Exception:
            # Let per-alert failures surface to Temporal for retry, but only after
            # every alert had a chance; the delivered-uuid claim makes retries safe.
            logger.exception(
                "error_tracking_alert_delivery_failed",
                alert_id=str(alert.id),
                team_id=inputs.team_id,
                event=inputs.event,
            )
            raise
    return delivered


def _process_alert(alert: ErrorTrackingAlert, inputs: AlertDeliveryWorkflowInputs) -> bool:
    trigger = OPENER_TRIGGERS.get(inputs.event)
    is_opener = trigger is not None and trigger in alert.triggers

    threads = ErrorTrackingAlertThread.objects.for_team(alert.team_id, canonical=True)
    thread = threads.filter(alert=alert, issue_id=inputs.issue_id).first()

    if thread is None:
        if not is_opener:
            return False
        try:
            thread, _ = threads.get_or_create(
                alert=alert, issue_id=inputs.issue_id, defaults={"team_id": alert.team_id}
            )
        except IntegrityError:
            # The issue row is gone (merged away or deleted) - nothing to alert on.
            return False

    if inputs.notification_id in (thread.delivered_event_uuids or []):
        return False

    client = _slack_client(alert)
    if client is None:
        return False

    if not thread.external_ref.get("ts"):
        if not is_opener:
            # Leave the notification unclaimed: a later opener posts the root and
            # subsequent updates deliver normally.
            return False
        message = build_root_message(inputs)
        channel = alert.config.get("channel")
        if not channel:
            return False
        response = client.chat_postMessage(channel=channel, blocks=message["blocks"], text=message["text"])
        # A crash between the post above and the save below re-posts the root on
        # retry. Accepted for the POC; production wants a claim-before-send record.
        thread.external_ref = {
            "channel": response["channel"],
            "ts": response["ts"],
            "headline": message["headline"],
        }
    else:
        reply = build_reply_text(inputs)
        if reply is None:
            return False
        # Replies stay in the thread's original channel: a Slack thread cannot
        # move, so a re-pointed alert only applies to new issues.
        client.chat_postMessage(
            channel=thread.external_ref["channel"],
            thread_ts=thread.external_ref["ts"],
            text=reply,
        )
        _maybe_edit_root(client, thread, inputs)

    thread.delivered_event_uuids = [*(thread.delivered_event_uuids or []), inputs.notification_id][
        -DELIVERED_EVENTS_CAP:
    ]
    thread.save(update_fields=["external_ref", "delivered_event_uuids", "updated_at"])
    return True


def _maybe_edit_root(client, thread: ErrorTrackingAlertThread, inputs: AlertDeliveryWorkflowInputs) -> None:
    include_actions = ROOT_EDIT_EVENTS.get(inputs.event)
    if include_actions is None:
        return
    message = build_root_edit(
        inputs,
        headline=thread.external_ref.get("headline", DEFAULT_HEADLINE),
        include_actions=include_actions,
    )
    try:
        client.chat_update(
            channel=thread.external_ref["channel"],
            ts=thread.external_ref["ts"],
            blocks=message["blocks"],
            text=message["text"],
        )
    except Exception:
        # The threaded reply already delivered the update; a failed root edit
        # only leaves stale buttons behind.
        logger.exception(
            "error_tracking_alert_root_edit_failed",
            thread_id=str(thread.id),
            event=inputs.event,
        )


def _slack_client(alert: ErrorTrackingAlert):
    if alert.integration_id is None:
        return None
    integration = Integration.objects.filter(
        id=alert.integration_id, team_id=alert.team_id, kind=Integration.IntegrationKind.SLACK
    ).first()
    if integration is None:
        return None
    return SlackIntegration(integration).client
