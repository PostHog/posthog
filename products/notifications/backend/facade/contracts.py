from dataclasses import dataclass

from products.notifications.backend.facade.enums import NotificationType, Priority


@dataclass(frozen=True)
class NotificationData:
    recipient_id: int
    notification_type: NotificationType
    title: str
    body: str
    team_id: int
    priority: Priority = Priority.NORMAL
    source_type: str = ""
    source_id: str = ""
    source_url: str = ""
    actor_id: int | None = None
