from posthog.api.routing import RouterRegistry

from products.web_analytics.backend.presentation.views import WebAnalyticsViewSet
from products.web_analytics.backend.presentation.views.heatmaps_api import (
    HeatmapScreenshotViewSet,
    HeatmapViewSet,
    LegacyHeatmapViewSet,
    SavedHeatmapViewSet,
)
from products.web_analytics.backend.presentation.views.web_analytics_filter_preset import (
    WebAnalyticsFilterPresetViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    routers.root.register(r"heatmap", LegacyHeatmapViewSet, basename="heatmap")
    routers.register_legacy_dual_route(r"heatmaps", HeatmapViewSet, "environment_heatmaps", ["team_id"])
    routers.register_legacy_dual_route(
        r"heatmap_screenshots", HeatmapScreenshotViewSet, "environment_heatmap_screenshots", ["team_id"]
    )
    routers.register_legacy_dual_route(r"saved", SavedHeatmapViewSet, "environment_saved", ["team_id"])
    routers.register_legacy_dual_route(
        r"web_analytics_filter_presets",
        WebAnalyticsFilterPresetViewSet,
        "project_web_analytics_filter_preset",
        ["team_id"],
    )
    routers.register_legacy_dual_route(r"web_analytics", WebAnalyticsViewSet, "project_web_analytics", ["team_id"])
