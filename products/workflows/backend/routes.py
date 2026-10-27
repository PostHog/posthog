from django.urls import URLPattern

from posthog.api.routing import RouterRegistry
from posthog.ingress.sns.provider import build_sns_provider
from posthog.ingress.views import build_webhook_view
from posthog.utils import opt_slash_path

from products.workflows.backend.presentation.views import (
    email_drafts,
    hog_flow,
    hog_flow_template,
    people_imports,
    workflow_classifications,
    workflow_data_suggestions,
    workflow_message_opt_outs,
    workflow_scout_runs,
    workflow_sending_rules,
    workflow_setup,
    workflow_static_cohort_members,
    workflow_tasks,
    workflow_vision_requests,
)

# AWS SES tenant reputation events, delivered EventBridge -> SNS HTTPS subscription. Workflows owns
# the topic and its allowlist setting, so the route is mounted here rather than in core.
webhook_urlpatterns: list[URLPattern] = [
    opt_slash_path(
        "ses-events",
        build_webhook_view(build_sns_provider(topic_arns_setting="WORKFLOWS_SES_EVENTS_SNS_TOPIC_ARNS")),
    ),
]


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"hog_flows", hog_flow.HogFlowViewSet, "project_hog_flows", ["team_id"])
    routers.projects.register(
        r"workflow_tasks", workflow_tasks.WorkflowTaskViewSet, "project_workflow_tasks", ["team_id"]
    )
    routers.projects.register(
        r"workflow_data_suggestions",
        workflow_data_suggestions.WorkflowDataSuggestionsViewSet,
        "project_workflow_data_suggestions",
        ["team_id"],
    )
    routers.projects.register(
        r"workflow_sending_rules",
        workflow_sending_rules.WorkflowSendingRulesViewSet,
        "project_workflow_sending_rules",
        ["team_id"],
    )
    routers.projects.register(
        r"workflow_setup", workflow_setup.WorkflowSetupViewSet, "project_workflow_setup", ["team_id"]
    )
    routers.projects.register(
        r"workflow_scout_runs",
        workflow_scout_runs.WorkflowScoutRunViewSet,
        "project_workflow_scout_runs",
        ["team_id"],
    )
    routers.projects.register(
        r"workflow_email_drafts",
        email_drafts.WorkflowEmailDraftViewSet,
        "project_workflow_email_drafts",
        ["team_id"],
    )
    routers.projects.register(
        r"workflow_classifications",
        workflow_classifications.WorkflowClassificationViewSet,
        "project_workflow_classifications",
        ["team_id"],
    )
    routers.projects.register(
        r"workflow_people_imports",
        people_imports.WorkflowPeopleImportViewSet,
        "project_workflow_people_imports",
        ["team_id"],
    )
    routers.projects.register(
        r"workflow_vision_requests",
        workflow_vision_requests.WorkflowVisionRequestViewSet,
        "project_workflow_vision_requests",
        ["team_id"],
    )
    routers.projects.register(
        r"workflow_static_cohort_members",
        workflow_static_cohort_members.WorkflowStaticCohortMemberViewSet,
        "project_workflow_static_cohort_members",
        ["team_id"],
    )
    routers.projects.register(
        r"workflow_message_opt_outs",
        workflow_message_opt_outs.WorkflowMessageOptOutViewSet,
        "project_workflow_message_opt_outs",
        ["team_id"],
    )
    routers.projects.register(
        r"hog_flow_templates",
        hog_flow_template.HogFlowTemplateViewSet,
        "project_hog_flow_templates",
        ["team_id"],
    )
    routers.root.register(
        r"public_hog_flow_templates",
        hog_flow_template.PublicHogFlowTemplateViewSet,
        "public_hog_flow_templates",
    )
