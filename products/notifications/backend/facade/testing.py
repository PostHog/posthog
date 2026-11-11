"""Test-support facade for notifications.

Products that notify through ``facade.api`` assert on the stored event in their tests. They
read it here instead of importing the model.
"""

from posthog.dataclasses import frozen

from products.notifications.backend.models import NotificationEvent


@frozen
class StoredNotification:
    notification_type: str
    title: str
    body: str
    resource_id: str
    source_url: str
    resolved_user_ids: list[int]


def _stored(event: NotificationEvent) -> StoredNotification:
    return StoredNotification(
        notification_type=event.notification_type,
        title=event.title,
        body=event.body,
        resource_id=event.resource_id,
        source_url=event.source_url,
        resolved_user_ids=list(event.resolved_user_ids),
    )


def stored_notification_for_resource(*, resource_type: str, resource_id: str) -> StoredNotification:
    return _stored(NotificationEvent.objects.get(resource_type=resource_type, resource_id=resource_id))


def stored_notifications_for_team(team_id: int) -> list[StoredNotification]:
    return [_stored(event) for event in NotificationEvent.objects.filter(team_id=team_id).order_by("created_at")]
