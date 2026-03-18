from products.notifications.backend.facade.contracts import NotificationData
from products.notifications.backend.facade.enums import NotificationResourceType, NotificationType, Priority, TargetType

__all__ = [
    "create_notification",
    "NotificationData",
    "NotificationResourceType",
    "NotificationType",
    "Priority",
    "TargetType",
]


def create_notification(data: NotificationData) -> None:
    raise NotImplementedError("Notification creation will be implemented in the backend PR")
