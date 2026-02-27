import json
from datetime import timedelta

from django.db import transaction

import structlog
import posthoganalytics

from posthog.models import User

from products.notifications.backend.facade.contracts import NotificationData
from products.notifications.backend.models import Notification

logger = structlog.get_logger(__name__)

REDIS_BUFFER_MAX = 49
REDIS_BUFFER_TTL = timedelta(days=1)


def _get_redis_client():
    from django.core.cache import cache

    return cache.client.get_client()


def _publish_to_redis(notification: Notification) -> None:
    try:
        client = _get_redis_client()
        channel = f"notifications:{notification.team_id}:{notification.recipient_id}"
        buffer_key = f"notification_buffer:{notification.team_id}:{notification.recipient_id}"

        payload = json.dumps(
            {
                "id": notification.id,
                "notification_type": notification.notification_type,
                "priority": notification.priority,
                "title": notification.title,
                "body": notification.body,
                "source_type": notification.source_type,
                "source_id": notification.source_id,
                "source_url": notification.source_url,
                "actor_id": notification.actor_id,
                "created_at": notification.created_at.isoformat(),
            }
        )

        pipe = client.pipeline()
        pipe.publish(channel, payload)
        pipe.lpush(buffer_key, payload)
        pipe.ltrim(buffer_key, 0, REDIS_BUFFER_MAX)
        pipe.expire(buffer_key, int(REDIS_BUFFER_TTL.total_seconds()))
        pipe.execute()
    except Exception:
        logger.exception("notifications.redis_publish_failed", notification_id=notification.id)


def create_notification(data: NotificationData) -> Notification | None:
    try:
        recipient = User.objects.get(id=data.recipient_id)
    except User.DoesNotExist:
        logger.warning("notifications.recipient_not_found", recipient_id=data.recipient_id)
        return None

    if not posthoganalytics.feature_enabled(
        "real-time-notifications",
        recipient.distinct_id,
        groups={"organization": str(recipient.current_organization_id or "")},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    ):
        return None

    notification = Notification.objects.create(
        recipient=recipient,
        notification_type=data.notification_type,
        priority=data.priority,
        title=data.title,
        body=data.body,
        source_type=data.source_type,
        source_id=data.source_id,
        source_url=data.source_url,
        actor_id=data.actor_id,
        team_id=data.team_id,
    )

    transaction.on_commit(lambda: _publish_to_redis(notification))

    return notification
