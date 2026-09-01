from posthog.api.routing import RouterRegistry

from products.replay_vision.backend.api import (
    ReplayObservationViewSet,
    ReplayScannerBackfillViewSet,
    ReplayScannerPromptSuggestionViewSet,
    ReplayScannerViewSet,
    ScannerScoutReportViewSet,
    ScannerScoutViewSet,
    SessionReplayObservationViewSet,
    VisionActionRunViewSet,
    VisionActionViewSet,
    VisionAlertViewSet,
    VisionQuotaViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    project_vision_scanners_router = routers.projects.register(
        r"vision/scanners", ReplayScannerViewSet, "project_vision_scanners", ["team_id"]
    )
    project_vision_scanners_router.register(
        r"scouts",
        ScannerScoutViewSet,
        "project_vision_scanner_scouts",
        ["team_id", "scanner_id"],
    )
    project_vision_scanners_router.register(
        r"scout_reports",
        ScannerScoutReportViewSet,
        "project_vision_scanner_scout_reports",
        ["team_id", "scanner_id"],
    )
    project_vision_scanners_router.register(
        r"observations", ReplayObservationViewSet, "project_vision_scanner_observations", ["team_id", "scanner_id"]
    )
    project_vision_scanners_router.register(
        r"backfills", ReplayScannerBackfillViewSet, "project_vision_scanner_backfills", ["team_id", "scanner_id"]
    )
    project_vision_scanners_router.register(
        r"prompt_suggestions",
        ReplayScannerPromptSuggestionViewSet,
        "project_vision_scanner_prompt_suggestions",
        ["team_id", "scanner_id"],
    )
    routers.projects.register(
        r"vision/observations", SessionReplayObservationViewSet, "project_vision_observations", ["team_id"]
    )
    routers.projects.register(r"vision/quota", VisionQuotaViewSet, "project_vision_quota", ["team_id"])
    routers.projects.register(r"vision/alerts", VisionAlertViewSet, "project_vision_alerts", ["team_id"])
    project_vision_actions_router = routers.projects.register(
        r"vision/actions", VisionActionViewSet, "project_vision_actions", ["team_id"]
    )
    project_vision_actions_router.register(
        r"runs", VisionActionRunViewSet, "project_vision_action_runs", ["team_id", "vision_action_id"]
    )
