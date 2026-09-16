from django.urls import URLPattern

from posthog.api.routing import RouterRegistry
from posthog.ingress.sns.provider import build_sns_provider
from posthog.ingress.views import build_webhook_view
from posthog.utils import opt_slash_path

from products.workflows.backend.api import hog_flow, hog_flow_template, workflow_scout_runs, workflow_tasks

# AWS SES tenant reputation events, delivered EventBridge -> SNS HTTPS subscription. Workflows owns
# the topic and its allowlist setting, so the route is mounted here rather than in core.
urlpatterns: list[URLPattern] = [
    opt_slash_path(
        "webhooks/workflows/ses-events",
        build_webhook_view(build_sns_provider(topic_arns_setting="WORKFLOWS_SES_EVENTS_SNS_TOPIC_ARNS")),
    ),
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
