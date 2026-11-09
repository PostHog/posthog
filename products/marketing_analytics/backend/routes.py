from posthog.api.routing import RouterRegistry

from products.marketing_analytics.backend.api import MarketingAnalyticsViewSet
from products.marketing_analytics.backend.recommendation_dismissal_api import RecommendationDismissalViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"marketing_analytics",
        MarketingAnalyticsViewSet,
        "project_marketing_analytics",
        ["team_id"],
    )
    routers.projects.register(
        r"marketing_analytics_recommendation_dismissals",
        RecommendationDismissalViewSet,
        "project_marketing_analytics_recommendation_dismissals",
        ["team_id"],
    )
