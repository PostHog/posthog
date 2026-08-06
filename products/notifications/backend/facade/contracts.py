from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from products.notifications.backend.facade.enums import (
    NotificationResourceType,
    NotificationType,
    Priority,
    SourceType,
    TargetType,
)

if TYPE_CHECKING:
    from products.notifications.backend.resolvers import RecipientsResolver


@dataclass(frozen=True)
class NotificationData:
    notification_type: NotificationType
    title: str
    body: str
    target_type: TargetType
    target_id: str
    team_id: int | None = None
    organization_id: UUID | None = None
    resource_type: NotificationResourceType | None = None
    resource_id: str = ""
    source_url: str = ""
    source_type: SourceType | None = None
    source_id: str | None = None
    priority: Priority = Priority.NORMAL
    metadata: dict[str, Any] | None = None
    resolver: RecipientsResolver | None = field(default=None, compare=False)
