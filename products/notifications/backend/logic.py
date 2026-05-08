from django.db import transaction

import structlog
import posthoganalytics

from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_NOTIFICATION_EVENTS
from posthog.models import Team, User

from products.notifications.backend.cache import invalidate_unread_count_for_users
from products.notifications.backend.facade.contracts import NotificationData
from products.notifications.backend.facade.enums import (
    AC_RESOURCE_TYPES,
    NotificationOnlyResourceType,
    NotificationType,
)
from products.notifications.backend.models import NotificationEvent
from products.notifications.backend.resolvers import RecipientsResolver

logger = structlog.get_logger(__name__)


def _publish_to_kafka(event: NotificationEvent) -> None:
    try:
        producer = get_producer(topic=KAFKA_NOTIFICATION_EVENTS)
        producer.produce(
            topic=KAFKA_NOTIFICATION_EVENTS,
            data={
                "id": str(event.id),
                "organization_id": str(event.organization_id),
                "team_id": event.team_id,
                "notification_type": event.notification_type,
                "priority": event.priority,
                "title": event.title,
                "body": event.body,
                "resource_type": event.resource_type or "",
                "source_url": event.source_url,
                "source_type": event.source_type,
                "source_id": event.source_id,
                "resolved_user_ids": event.resolved_user_ids,
                "created_at": event.created_at.isoformat(),
            },
            key=str(event.organization_id),
        )
    except Exception:
        logger.exception("notifications.kafka_publish_failed", event_id=event.id)


def _filter_by_user_preferences(
    user_ids: list[int],
    notification_type: NotificationType,
    team_id: int,
) -> list[int]:
    if not user_ids:
        return user_ids
    rows = User.objects.filter(id__in=user_ids).values_list("id", "partial_notification_settings")
    type_key = notification_type.value
    team_key = str(team_id)

    def _is_disabled(settings: dict | None) -> bool:
        realtime = (settings or {}).get("realtime_notifications_disabled") or {}
        type_map = realtime.get(type_key) or {}
        return bool(type_map.get(team_key, False))

    return [uid for uid, settings in rows if not _is_disabled(settings)]


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

    # Per-user pref filter must run AFTER AC — prefs cannot override access denials.
    resolved_user_ids = _filter_by_user_preferences(
        resolved_user_ids,
        notification_type=data.notification_type,
        team_id=data.team_id,
    )

    if not resolved_user_ids:
        logger.warning(
            "notifications.no_recipients",
            target_type=data.target_type,
            target_id=data.target_id,
        )
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
        source_type=data.source_type,
        source_id=data.source_id,
        target_type=data.target_type,
        target_id=data.target_id,
        resolved_user_ids=resolved_user_ids,
    )

    def _on_commit() -> None:
        _publish_to_kafka(event)
        invalidate_unread_count_for_users(resolved_user_ids, organization.id)

    transaction.on_commit(_on_commit)

    return event
