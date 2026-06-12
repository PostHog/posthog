from posthog.api.routing import RouterRegistry

from products.workflows.backend.api import hog_flow, hog_flow_template


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(r"hog_flows", hog_flow.HogFlowViewSet, "environment_hog_flows", ["team_id"])
    routers.register_legacy_dual_route(
        r"hog_flow_templates",
        hog_flow_template.HogFlowTemplateViewSet,
        "environment_hog_flow_templates",
        ["team_id"],
    )
