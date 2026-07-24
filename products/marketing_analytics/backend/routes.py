from posthog.api.routing import RouterRegistry

from products.marketing_analytics.backend.api import MarketingAnalyticsViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"marketing_analytics",
        MarketingAnalyticsViewSet,
        "project_marketing_analytics",
        ["team_id"],
    )
