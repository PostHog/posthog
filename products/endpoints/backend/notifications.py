from posthog.exceptions_capture import capture_exception
from posthog.models import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.endpoints.backend.models import Endpoint, EndpointVersion
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    RecipientsResolver,
    TargetType,
    create_notification,
)


class _EndpointViewers(RecipientsResolver):
    def __init__(self, endpoint: Endpoint) -> None:
        self.endpoint = endpoint

    def resolve(self, target_type: TargetType, target_id: str, team_id: int | None) -> list[int]:
        if team_id != self.endpoint.team_id:
            return []
        user_ids = super().resolve(target_type, target_id, team_id)
        team = self.endpoint.team
        users = User.objects.filter(id__in=user_ids).filter(id__in=team.all_users_with_access().values("id"))
        viewers = []
        for user in users:
            try:
                access = UserAccessControl(user, team)
                if access.is_organization_admin or access.check_access_level_for_object(self.endpoint, "viewer"):
                    viewers.append(user.pk)
            except Exception:
                capture_exception()
        return viewers


def notify_materialization_hibernated(version: EndpointVersion) -> None:
    if version.materialization_hibernated_at is None:
        return
    endpoint = version.endpoint
    create_notification(
        NotificationData(
            team_id=endpoint.team_id,
            notification_type=NotificationType.MATERIALIZATION_HIBERNATED,
            priority=Priority.NORMAL,
            title=f"Materialization paused for {endpoint.name} v{version.version}"[:255],
            body="This version has not been called with an API key in 30 days. "
            "The next API-key call requests materialization again. "
            "Calls run the full query until results are ready. You can also resume materialization in its settings.",
            target_type=TargetType.TEAM,
            target_id=str(endpoint.team_id),
            resource_type="endpoint",
            resource_id=str(endpoint.pk),
            source_url=f"/project/{endpoint.team_id}/endpoints/{endpoint.name}?version={version.version}",
            source_id=str(version.pk),
            idempotency_key=f"endpoint-hibernate-{version.pk}-{version.materialization_hibernated_at.isoformat()}",
            resolver=_EndpointViewers(endpoint),
        )
    )
