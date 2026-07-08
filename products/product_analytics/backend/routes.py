from posthog.api import sharing
from posthog.api.routing import RouterRegistry
from posthog.settings import EE_AVAILABLE

import products.alerts.backend.api.alert as alert
from products.product_analytics.backend.api.insight import InsightViewSet
from products.product_analytics.backend.api.insight_variable import InsightVariableViewSet


def register_routes(routers: RouterRegistry) -> None:
    # EE installs override the insights viewset with EnterpriseInsightsViewSet.
    # The non-EE InsightViewSet is the fallback. Either way, the route name and
    # nested sub-routes (sharing, thresholds) stay identical.
    insights_viewset: type[InsightViewSet]
    if EE_AVAILABLE:
        from ee.clickhouse.views.insights import EnterpriseInsightsViewSet

        insights_viewset = EnterpriseInsightsViewSet
    else:
        insights_viewset = InsightViewSet

    legacy_project_insights_router, environment_insights_router = routers.register_legacy_dual_route(
        r"insights", insights_viewset, "environment_insights", ["team_id"]
    )

    # SharingConfigurationViewSet is shared (core); the route lives under
    # insights/<id>/sharing — product_analytics owns the sub-route.
    environment_insights_router.register(
        r"sharing",
        sharing.SharingConfigurationViewSet,
        "environment_insight_sharing",
        ["team_id", "insight_id"],
    )
    legacy_project_insights_router.register(
        r"sharing",
        sharing.SharingConfigurationViewSet,
        "project_insight_sharing",
        ["team_id", "insight_id"],
    )

    # ThresholdViewSet is owned by the alerts product but nests under insights.
    environment_insights_router.register(
        "thresholds",
        alert.ThresholdViewSet,
        "environment_insight_thresholds",
        ["team_id", "insight_id"],
    )
    legacy_project_insights_router.register(
        "thresholds",
        alert.ThresholdViewSet,
        "project_insight_thresholds",
        ["team_id", "insight_id"],
    )

    routers.register_legacy_dual_route(
        r"insight_variables",
        InsightVariableViewSet,
        "environment_insight_variables",
        ["team_id"],
    )
