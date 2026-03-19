import os
import json

from django.db import transaction

import redis
import structlog
import posthoganalytics

from posthog.models import Team

from products.notifications.backend.facade.contracts import NotificationData
from products.notifications.backend.facade.enums import AC_RESOURCE_TYPES, NotificationOnlyResourceType
from products.notifications.backend.models import NotificationEvent
from products.notifications.backend.resolvers import RecipientsResolver

logger = structlog.get_logger(__name__)


def _get_livestream_redis_client():
    """Connect to the same Redis instance as the Go livestream service.
    This is separate from Django's default cache Redis."""
    host = os.getenv("LIVESTREAM_REDIS_ADDRESS", "localhost")
    port = int(os.getenv("LIVESTREAM_REDIS_PORT", "6379"))
    return redis.Redis(host=host, port=port)


def _publish_to_redis(event: NotificationEvent) -> None:
    try:
        client = _get_livestream_redis_client()
        channel = f"notifications:{event.organization_id}"

        payload = json.dumps(
            {
                "id": str(event.id),
                "notification_type": event.notification_type,
                "priority": event.priority,
                "title": event.title,
                "body": event.body,
                "resource_type": event.resource_type or "",
                "source_url": event.source_url,
                "resolved_user_ids": event.resolved_user_ids,
                "created_at": event.created_at.isoformat(),
            }
        )

        client.publish(channel, payload)
    except Exception:
        logger.exception("notifications.redis_publish_failed", event_id=event.id)


def create_notification(data: NotificationData) -> NotificationEvent | None:
    try:
        team = Team.objects.select_related("organization").get(id=data.team_id)
    except Team.DoesNotExist:
        logger.warning("notifications.team_not_found", team_id=data.team_id)
        return None

    organization = team.organization

    if not posthoganalytics.feature_enabled(
        "real-time-notifications",
        str(organization.id),
        groups={"organization": str(organization.id)},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    ):
        return None

    resolver = data.resolver or RecipientsResolver()
    resolved_user_ids = resolver.resolve(data.target_type, data.target_id, data.team_id)

    if data.resource_type and str(data.resource_type) in AC_RESOURCE_TYPES:
        resolved_user_ids = resolver.filter_by_access_control(resolved_user_ids, str(data.resource_type), team)

    if not resolved_user_ids:
        logger.warning("notifications.no_recipients", target_type=data.target_type, target_id=data.target_id)
        return None

    event = NotificationEvent.objects.create(
        organization=organization,
        team=team,
        notification_type=data.notification_type,
        priority=data.priority,
        title=data.title,
        body=data.body,
        resource_type=data.resource_type.value
        if isinstance(data.resource_type, NotificationOnlyResourceType)
        else data.resource_type,
        resource_id=data.resource_id,
        source_url=data.source_url,
        target_type=data.target_type,
        target_id=data.target_id,
        resolved_user_ids=resolved_user_ids,
    )

    transaction.on_commit(lambda: _publish_to_redis(event))

    return event
