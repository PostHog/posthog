from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from products.notifications.backend.facade.enums import NotificationResourceType, NotificationType, Priority, TargetType

if TYPE_CHECKING:
    from products.notifications.backend.resolvers import RecipientsResolver


@dataclass(frozen=True)
class NotificationData:
    team_id: int
    notification_type: NotificationType
    title: str
    body: str
    target_type: TargetType
    target_id: str
    resource_type: NotificationResourceType | None = None
    resource_id: str = ""
    source_url: str = ""
    priority: Priority = Priority.NORMAL
    resolver: RecipientsResolver | None = field(default=None, compare=False)
