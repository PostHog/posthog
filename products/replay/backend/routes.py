from posthog.api.routing import RouterRegistry

from products.replay.backend.api import SessionRecordingExportViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"session_recording_exports",
        SessionRecordingExportViewSet,
        "session_recording_exports",
        ["team_id"],
    )
