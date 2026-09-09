from posthog.api.routing import RouterRegistry

from products.workflows.backend.api import (
    hog_flow,
    hog_flow_template,
    workflow_customer_tasks,
    workflow_scout_runs,
    workflow_tasks,
)


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"workflow_customer_tasks",
        workflow_customer_tasks.WorkflowCustomerTaskViewSet,
        "project_workflow_customer_tasks",
        ["team_id"],
    )
    routers.projects.register(r"hog_flows", hog_flow.HogFlowViewSet, "project_hog_flows", ["team_id"])
    routers.projects.register(
        r"workflow_tasks", workflow_tasks.WorkflowTaskViewSet, "project_workflow_tasks", ["team_id"]
    )
    routers.projects.register(
        r"workflow_scout_runs",
        workflow_scout_runs.WorkflowScoutRunViewSet,
        "project_workflow_scout_runs",
        ["team_id"],
    )
    routers.projects.register(
        r"hog_flow_templates",
        hog_flow_template.HogFlowTemplateViewSet,
        "project_hog_flow_templates",
        ["team_id"],
    )
