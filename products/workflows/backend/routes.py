from django.urls import URLPattern

from posthog.api.routing import RouterRegistry
from posthog.utils import opt_slash_path

from products.workflows.backend.api import hog_flow, hog_flow_template, workflow_scout_runs, workflow_tasks
from products.workflows.backend.api.ses_events_webhook import ses_tenant_events_webhook

# AWS SES tenant reputation events (EventBridge -> SNS HTTPS subscription)
urlpatterns: list[URLPattern] = [
    opt_slash_path("webhooks/workflows/ses-events", ses_tenant_events_webhook),
]


def register_routes(routers: RouterRegistry) -> None:
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
