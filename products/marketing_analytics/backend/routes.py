from posthog.api.routing import RouterRegistry

from products.marketing_analytics.backend.api import MarketingAnalyticsViewSet
from products.marketing_analytics.backend.presentation.recommendation_resolutions import RecommendationResolutionViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"marketing_analytics",
        MarketingAnalyticsViewSet,
        "project_marketing_analytics",
        ["team_id"],
    )
    routers.projects.register(
        r"marketing_analytics_recommendation_resolutions",
        RecommendationResolutionViewSet,
        "project_marketing_analytics_recommendation_resolutions",
        ["team_id"],
    )
