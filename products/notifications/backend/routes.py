from posthog.api.routing import RouterRegistry

from products.notifications.backend.presentation.agent_notices import AgentNoticeViewSet
from products.notifications.backend.presentation.views import NotificationsViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(r"notifications", NotificationsViewSet, "project_notifications", ["team_id"])
    routers.projects.register(r"agent_notices", AgentNoticeViewSet, "project_agent_notices", ["team_id"])
