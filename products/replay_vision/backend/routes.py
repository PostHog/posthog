from posthog.api.routing import RouterRegistry

from products.replay_vision.backend.api import (
    ReplayObservationViewSet,
    ReplayScannerViewSet,
    SessionReplayObservationViewSet,
    VisionActionRunViewSet,
    VisionActionViewSet,
    VisionQuotaViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    project_vision_scanners_router, environment_vision_scanners_router = routers.register_legacy_dual_route(
        r"vision/scanners", ReplayScannerViewSet, "project_vision_scanners", ["team_id"]
    )
    environment_vision_scanners_router.register(
        r"observations", ReplayObservationViewSet, "environment_vision_scanner_observations", ["team_id", "scanner_id"]
    )
    project_vision_scanners_router.register(
        r"observations", ReplayObservationViewSet, "project_vision_scanner_observations", ["team_id", "scanner_id"]
    )
    routers.register_legacy_dual_route(
        r"vision/observations", SessionReplayObservationViewSet, "project_vision_observations", ["team_id"]
    )
    routers.register_legacy_dual_route(r"vision/quota", VisionQuotaViewSet, "project_vision_quota", ["team_id"])
    project_vision_actions_router = routers.projects.register(
        r"vision/actions", VisionActionViewSet, "project_vision_actions", ["team_id"]
    )
    project_vision_actions_router.register(
        r"runs", VisionActionRunViewSet, "project_vision_action_runs", ["team_id", "vision_action_id"]
    )
