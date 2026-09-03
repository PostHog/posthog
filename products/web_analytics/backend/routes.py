from posthog.api.routing import RouterRegistry

from products.web_analytics.backend.api import WebAnalyticsViewSet
from products.web_analytics.backend.api.heatmaps_api import (
    HeatmapScreenshotViewSet,
    HeatmapViewSet,
    LegacyHeatmapViewSet,
    SavedHeatmapViewSet,
)
from products.web_analytics.backend.api.web_analytics_achievements import WebAnalyticsAchievementsViewSet
from products.web_analytics.backend.api.web_analytics_filter_preset import WebAnalyticsFilterPresetViewSet
from products.web_analytics.backend.api.web_analytics_path_cleaning_suggestions import (
    WebAnalyticsPathCleaningSuggestionViewSet,
)
from products.web_analytics.backend.presentation.views.content_autopilot import (
    ContentAutopilotProposalViewSet,
    ContentAutopilotRunViewSet,
    ContentAutopilotSiteProfileViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    routers.root.register(r"heatmap", LegacyHeatmapViewSet, basename="heatmap")
    routers.projects.register(r"heatmaps", HeatmapViewSet, "project_heatmaps", ["team_id"])
    routers.projects.register(
        r"heatmap_screenshots", HeatmapScreenshotViewSet, "project_heatmap_screenshots", ["team_id"]
    )
    routers.projects.register(r"saved", SavedHeatmapViewSet, "project_saved", ["team_id"])
    routers.projects.register(
        r"web_analytics_filter_presets",
        WebAnalyticsFilterPresetViewSet,
        "project_web_analytics_filter_preset",
        ["team_id"],
    )
    routers.projects.register(r"web_analytics", WebAnalyticsViewSet, "project_web_analytics", ["team_id"])
    routers.projects.register(
        r"web_analytics_content_autopilot_profiles",
        ContentAutopilotSiteProfileViewSet,
        "project_web_analytics_content_autopilot_profiles",
        ["team_id"],
    )
    routers.projects.register(
        r"web_analytics_content_autopilot_runs",
        ContentAutopilotRunViewSet,
        "project_web_analytics_content_autopilot_runs",
        ["team_id"],
    )
    routers.projects.register(
        r"web_analytics_content_autopilot_proposals",
        ContentAutopilotProposalViewSet,
        "project_web_analytics_content_autopilot_proposals",
        ["team_id"],
    )
    routers.projects.register(
        r"web_analytics_achievements",
        WebAnalyticsAchievementsViewSet,
        "project_web_analytics_achievements",
        ["team_id"],
    )
    routers.projects.register(
        r"web_analytics_path_cleaning_suggestions",
        WebAnalyticsPathCleaningSuggestionViewSet,
        "project_web_analytics_path_cleaning_suggestions",
        ["team_id"],
    )
