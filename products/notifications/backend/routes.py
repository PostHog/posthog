from posthog.api.routing import RouterRegistry

from products.notifications.backend.presentation.views import NotificationsViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.environments.register(r"notifications", NotificationsViewSet, "environment_notifications", ["team_id"])
