from posthog.api.routing import RouterRegistry

from products.slack_app.backend.views import SlackAppWorkspaceSetupViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"slack_app_workspace_setup",
        SlackAppWorkspaceSetupViewSet,
        "project_slack_app_workspace_setup",
        ["team_id"],
    )
