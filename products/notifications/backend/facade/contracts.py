from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from products.notifications.backend.facade.enums import (
    NotificationResourceType,
    NotificationType,
    Priority,
    SourceType,
    TargetType,
)

if TYPE_CHECKING:
    from posthog.models import Team


class RecipientsResolverProtocol(Protocol):
    """What notification delivery calls on a custom resolver.

    backend.resolvers.RecipientsResolver implements it, and products subclass that class to
    change who receives a notification.
    """

    def resolve(self, target_type: TargetType, target_id: str, team_id: int | None) -> list[int]: ...

    def filter_by_access_control(self, user_ids: list[int], resource_type: str, team: Team) -> list[int]: ...


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
    resolver: RecipientsResolverProtocol | None = field(default=None, compare=False)
    idempotency_key: str | None = None
