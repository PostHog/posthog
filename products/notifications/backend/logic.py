from typing import Any
from uuid import UUID

from django.db import transaction

import structlog
import posthoganalytics

from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_NOTIFICATION_EVENTS
from posthog.models import Organization, OrganizationDomain, Team, User

from products.access_control.backend.facade.user_access_control import ACCESS_CONTROL_RESOURCES, UserAccessControl
from products.notifications.backend.cache import invalidate_unread_count_for_users
from products.notifications.backend.facade.contracts import NotificationData
from products.notifications.backend.facade.enums import (
    RESOURCE_EDITED_EVENT_TYPE,
    NotificationOnlyResourceType,
    NotificationType,
    TargetType,
)
from products.notifications.backend.models import NotificationEvent
from products.notifications.backend.pubsub import publish_notification_payload
from products.notifications.backend.resolvers import RecipientsResolver

logger = structlog.get_logger(__name__)


def _realtime_payload(event: NotificationEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "organization_id": str(event.organization_id),
        "team_id": event.team_id,
        "notification_type": event.notification_type,
        "priority": event.priority,
        "title": event.title,
        "body": event.body,
        "resource_type": event.resource_type or "",
        # The client groups rows by (type, target, resource) — a live-pushed notification
        # without resource_id would land in the wrong group until the next refetch.
        "resource_id": event.resource_id or "",
        "source_url": event.source_url,
        "source_type": event.source_type,
        "source_id": event.source_id,
        "resolved_user_ids": event.resolved_user_ids,
        "created_at": event.created_at.isoformat(),
    }


def _publish_to_kafka(event: NotificationEvent, payload: dict[str, Any]) -> None:
    try:
        producer = get_producer(topic=KAFKA_NOTIFICATION_EVENTS)
        producer.produce(
            topic=KAFKA_NOTIFICATION_EVENTS,
            data=payload,
            key=str(event.organization_id),
        )
    except Exception:
        logger.exception("notifications.kafka_publish_failed", event_id=event.id)


def _filter_to_active_members(user_ids: list[int], organization_id: UUID) -> list[int]:
    # Resolvers can return stored user IDs, such as alert subscribers. A user deactivated or removed after
    # that must stop receiving notifications, including over a stream that opened before the change.
    if not user_ids:
        return user_ids
    allowed = set(
        User.objects.filter(
            id__in=user_ids, is_active=True, organization_membership__organization_id=organization_id
        ).values_list("id", flat=True)
    )
    return [user_id for user_id in user_ids if user_id in allowed]


def can_receive_notifications(
    user_id: int, organization_id: UUID, team_id: int | None, *, domain_enforcement_exempt: bool
) -> bool:
    """Whether the user is an active member of the organization who can access the notification's project,
    and whom verified-domain enforcement allows."""
    user = User.objects.filter(
        id=user_id, is_active=True, organization_membership__organization_id=organization_id
    ).first()
    if user is None:
        return False
    if team_id is not None:
        team = Team.objects.filter(id=team_id, organization_id=organization_id).first()
        if team is None:
            return False
        user_access_control = UserAccessControl(user, team)
        if user_access_control.access_controls_supported and not user_access_control.has_project_access:
            return False
    if domain_enforcement_exempt:
        return True
    organization = Organization.objects.filter(id=organization_id).first()
    if organization is None:
        return False
    return not OrganizationDomain.objects.is_email_blocked_by_domain_enforcement(user.email, organization)


def _filter_by_user_preferences(
    user_ids: list[int],
    notification_type: NotificationType,
    team_id: int | None,
) -> list[int]:
    # Per-team preferences only apply to team-level notifications; org-level dispatch has no team key to gate on.
    if not user_ids or team_id is None:
        return user_ids
    rows = User.objects.filter(id__in=user_ids).values_list("id", "partial_notification_settings")
    type_key = notification_type.value
    team_key = str(team_id)

    def _is_disabled(settings: dict | None) -> bool:
        realtime = (settings or {}).get("realtime_notifications_disabled") or {}
        type_map = realtime.get(type_key) or {}
        return bool(type_map.get(team_key, False))

    return [uid for uid, settings in rows if not _is_disabled(settings)]


def has_been_dispatched(
    *,
    notification_type: NotificationType,
    target_type: TargetType,
    target_id: str,
    resource_id: str,
    source_id: str | None = None,
) -> bool:
    """Idempotency check used by dispatchers whose trigger can fire multiple times for the
    same logical event (e.g. Celery at-least-once retries, racing workers). Returns True if
    a matching NotificationEvent already exists, so the caller can skip a duplicate write.
    """
    return NotificationEvent.objects.filter(
        notification_type=notification_type.value,
        target_type=target_type.value,
        target_id=target_id,
        resource_id=resource_id,
        source_id=source_id,
    ).exists()


def publish_resource_edited(
    *,
    team: Team,
    resource_type: str,
    resource_id: str,
    updated_at: str,
    actor_user_id: int | None = None,
    ac_resource_type: str | None = None,
) -> None:
    """Push a transient "this resource was edited elsewhere" event over the realtime stream, so an
    open editor (e.g. the workflow builder) can refresh instead of clobbering edits made via MCP/API.

    Unlike create_notification this persists NO NotificationEvent row: it is editor-state sync, not an
    inbox notification — it must not appear in the popover, must not bump the unread count, and there
    are no user mute preferences to honour. It rides the same realtime transports as inbox notifications
    (Kafka → livestream, and Redis → the Django stream); both pass unknown fields through and filter
    delivery by resolved_user_ids.

    `resource_type` is the value the frontend matches on (e.g. "HogFlow"); `ac_resource_type` is the
    access-control scope used to drop recipients without viewer access (e.g. "hog_flow").
    """
    organization_id = team.organization_id

    if not posthoganalytics.feature_enabled(
        "real-time-notifications",
        str(organization_id),
        groups={"organization": str(organization_id)},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    ):
        return

    resolver = RecipientsResolver()
    recipient_user_ids = _filter_to_active_members(
        resolver.resolve(TargetType.TEAM, str(team.id), team.id), organization_id
    )
    if ac_resource_type and ac_resource_type in ACCESS_CONTROL_RESOURCES:
        recipient_user_ids = resolver.filter_by_access_control(recipient_user_ids, ac_resource_type, team)

    if not recipient_user_ids:
        return

    payload = {
        "organization_id": str(organization_id),
        "team_id": team.id,
        "notification_type": RESOURCE_EDITED_EVENT_TYPE,
        "resource_type": resource_type,
        "resource_id": str(resource_id),
        "updated_at": updated_at,
        "actor_user_id": actor_user_id,
        "resolved_user_ids": recipient_user_ids,
        "priority": "normal",
    }

    def _on_commit() -> None:
        try:
            producer = get_producer(topic=KAFKA_NOTIFICATION_EVENTS)
            producer.produce(topic=KAFKA_NOTIFICATION_EVENTS, data=payload, key=str(organization_id))
        except Exception:
            logger.exception("notifications.resource_edited_publish_failed", resource_id=str(resource_id))
        publish_notification_payload(organization_id, payload)

    transaction.on_commit(_on_commit)


def create_notification(data: NotificationData) -> NotificationEvent | None:
    team: Team | None = None
    if data.team_id is not None:
        try:
            team = Team.objects.select_related("organization").get(id=data.team_id)
        except Team.DoesNotExist:
            logger.warning("notifications.team_not_found", team_id=data.team_id)
            return None
        organization = team.organization
    elif data.organization_id is not None:
        try:
            organization = Organization.objects.get(id=data.organization_id)
        except Organization.DoesNotExist:
            logger.warning("notifications.organization_not_found", organization_id=data.organization_id)
            return None
    else:
        logger.warning("notifications.no_target_scope")
        return None

    if not posthoganalytics.feature_enabled(
        "real-time-notifications",
        str(organization.id),
        groups={"organization": str(organization.id)},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    ):
        return None

    resolver = data.resolver or RecipientsResolver()
    resolved_user_ids = _filter_to_active_members(
        resolver.resolve(data.target_type, data.target_id, data.team_id), organization.id
    )

    if team is not None and data.resource_type and str(data.resource_type) in ACCESS_CONTROL_RESOURCES:
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

    event_data = {
        "organization": organization,
        "team": team,
        "notification_type": data.notification_type,
        "priority": data.priority,
        "title": data.title,
        "body": data.body,
        "resource_type": data.resource_type.value
        if isinstance(data.resource_type, NotificationOnlyResourceType)
        else data.resource_type,
        "resource_id": data.resource_id,
        "source_url": data.source_url,
        "source_type": data.source_type,
        "source_id": data.source_id,
        "target_type": data.target_type,
        "target_id": data.target_id,
        "resolved_user_ids": resolved_user_ids,
        "metadata": data.metadata,
    }
    if data.idempotency_key:
        event, created = NotificationEvent.objects.get_or_create(
            organization_id=organization.id,
            team_id=data.team_id,
            idempotency_key=data.idempotency_key,
            defaults=event_data,
        )
        if not created:
            return event
    else:
        event = NotificationEvent.objects.create(**event_data)

    def _on_commit() -> None:
        payload = _realtime_payload(event)
        _publish_to_kafka(event, payload)
        invalidate_unread_count_for_users(resolved_user_ids, organization.id)
        publish_notification_payload(organization.id, payload)

    transaction.on_commit(_on_commit)

    return event
