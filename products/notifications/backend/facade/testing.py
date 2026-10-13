"""Test-support facade for notifications.

Products that notify through ``facade.api`` assert on the stored event in their tests. They
read it here instead of importing the model.
"""

from posthog.dataclasses import frozen

from products.notifications.backend.models import NotificationEvent


@frozen
class StoredNotification:
    title: str
    source_url: str
    resolved_user_ids: list[int]


def stored_notification_for_resource(*, resource_type: str, resource_id: str) -> StoredNotification:
    event = NotificationEvent.objects.get(resource_type=resource_type, resource_id=resource_id)
    return StoredNotification(
        title=event.title,
        source_url=event.source_url,
        resolved_user_ids=list(event.resolved_user_ids),
    )
