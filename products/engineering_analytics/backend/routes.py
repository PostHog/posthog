from posthog.api.routing import RouterRegistry

from products.engineering_analytics.backend.presentation.views import EngineeringAnalyticsViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"engineering_analytics",
        EngineeringAnalyticsViewSet,
        "project_engineering_analytics",
        ["project_id"],
    )
