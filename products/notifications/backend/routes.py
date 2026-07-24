from posthog.api.routing import RouterRegistry

from products.notifications.backend.presentation.views import NotificationsViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"notifications", NotificationsViewSet, "project_notifications", ["team_id"])
