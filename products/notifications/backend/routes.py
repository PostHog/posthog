from posthog.api.routing import RouterRegistry

from products.notifications.backend.presentation.views import NotificationsViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(r"notifications", NotificationsViewSet, "project_notifications", ["team_id"])
