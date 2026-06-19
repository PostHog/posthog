from posthog.api.routing import RouterRegistry

from products.desktop_recordings.backend.api import DesktopRecordingViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(
        r"desktop_recordings",
        DesktopRecordingViewSet,
        "project_desktop_recordings",
        ["team_id"],
    )
