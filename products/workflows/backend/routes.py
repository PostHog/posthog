from posthog.api.routing import RouterRegistry

from products.workflows.backend.api import hog_flow, hog_flow_action_template, hog_flow_template


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"hog_flows", hog_flow.HogFlowViewSet, "project_hog_flows", ["team_id"])
    routers.projects.register(
        r"hog_flow_templates",
        hog_flow_template.HogFlowTemplateViewSet,
        "project_hog_flow_templates",
        ["team_id"],
    )
    routers.projects.register(
        r"hog_flow_action_templates",
        hog_flow_action_template.HogFlowActionTemplateViewSet,
        "project_hog_flow_action_templates",
        ["team_id"],
    )
