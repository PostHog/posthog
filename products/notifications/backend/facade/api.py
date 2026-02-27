from products.notifications.backend.facade.contracts import NotificationData

__all__ = ["create_notification", "NotificationData"]


def create_notification(data: NotificationData) -> None:
    raise NotImplementedError("Notification creation will be implemented in the backend PR")
