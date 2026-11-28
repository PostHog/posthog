"""The SES receiving SNS topic. The handler only enqueues, so a message with a huge body never touches a web pod."""

import json
from typing import Any

import structlog

from posthog.ingress.contracts import WebhookDelivery

from products.workflows.backend.services.ses_tenant_events import confirm_sns_subscription
from products.workflows.backend.tasks.inbound_email import process_inbound_email_task

logger = structlog.get_logger(__name__)


def handle_inbound_email_delivery(delivery: WebhookDelivery) -> None:
    if delivery.event_type == "SubscriptionConfirmation":
        confirm_sns_subscription(delivery.payload)
        return
    if delivery.event_type != "Notification":
        return
    try:
        notification: Any = json.loads(delivery.payload.get("Message", ""))
    except (TypeError, ValueError):
        logger.warning("inbound_email_unreadable_notification", delivery_id=delivery.delivery_id)
        return
    if isinstance(notification, dict):
        # An error enqueuing costs the delivery its receipt, so SNS sends it again.
        process_inbound_email_task.delay(notification)
