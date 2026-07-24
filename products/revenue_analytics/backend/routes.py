from posthog.api.routing import RouterRegistry

import products.revenue_analytics.backend.api as revenue_analytics


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"revenue_analytics/taxonomy",
        revenue_analytics.RevenueAnalyticsTaxonomyViewSet,
        "project_revenue_analytics_taxonomy",
        ["team_id"],
    )
    routers.projects.register(
        r"revenue_analytics/joins",
        revenue_analytics.RevenueAnalyticsJoinViewSet,
        "project_revenue_analytics_joins",
        ["team_id"],
    )
