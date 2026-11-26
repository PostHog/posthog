from posthog.api.routing import RouterRegistry

from products.slack_app.backend.presentation.views import SlackAppSettingsViewSet, SlackAppWorkspaceSetupViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"slack_app_workspace_setup",
        SlackAppWorkspaceSetupViewSet,
        "project_slack_app_workspace_setup",
        ["team_id"],
    )
    routers.projects.register(
        r"slack_app_settings",
        SlackAppSettingsViewSet,
        "project_slack_app_settings",
        ["team_id"],
    )
