"""Analytics events for the notifications product.

These events are captured into PostHog's own regional analytics project (via
`get_regional_ph_client`) — not the customer's project. Concierge is a
PostHog-staff tool aimed at PostHog users, so deliveries are tracked in our
internal analytics so we can measure campaign reach and follow-up engagement.
"""

import structlog

from posthog.models import User
from posthog.ph_client import get_regional_ph_client

from products.notifications.backend.facade.enums import NotificationType
from products.notifications.backend.models import NotificationEvent

logger = structlog.get_logger(__name__)

CONCIERGE_DELIVERED_EVENT = "$concierge_notification_delivered"


def _build_properties(event: NotificationEvent) -> dict:
    return {
        "notification_id": str(event.id),
        "notification_type": event.notification_type,
        "priority": event.priority,
        "title": event.title,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "source_url": event.source_url,
        "source_type": event.source_type,
        "source_id": event.source_id,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "recipient_count": len(event.resolved_user_ids or []),
        "team_id": event.team_id,
        "organization_id": str(event.organization_id),
    }


def capture_notification_delivered(event: NotificationEvent) -> None:
    """Emit one `$concierge_notification_delivered` per resolved recipient.

    Only fires for concierge notifications. Failures are swallowed so a flaky
    analytics call never breaks notification delivery.
    """
    if event.notification_type != NotificationType.CONCIERGE.value:
        return

    user_ids: list[int] = event.resolved_user_ids or []
    if not user_ids:
        return

    client = get_regional_ph_client()
    if client is None:
        return

    properties = _build_properties(event)
    distinct_ids = User.objects.filter(id__in=user_ids).values_list("distinct_id", flat=True)

    try:
        for distinct_id in distinct_ids:
            if not distinct_id:
                continue
            try:
                client.capture(
                    distinct_id=distinct_id,
                    event=CONCIERGE_DELIVERED_EVENT,
                    properties=properties,
                )
            except Exception:
                logger.exception(
                    "notifications.concierge_capture_failed",
                    notification_id=str(event.id),
                    distinct_id=distinct_id,
                )
    finally:
        try:
            client.shutdown()
        except Exception:
            logger.exception("notifications.concierge_client_shutdown_failed")
