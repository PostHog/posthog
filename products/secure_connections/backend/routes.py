from posthog.api.routing import RouterRegistry

from products.secure_connections.backend.presentation.views import SecureConnectionViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"secure_connections",
        SecureConnectionViewSet,
        "project_secure_connections",
        ["team_id"],
    )
