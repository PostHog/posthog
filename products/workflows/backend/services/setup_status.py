"""Which messaging setup steps a project has done, in the order the setup wizard asks for them."""

from posthog.models import Team
from posthog.models.integration import Integration

from products.messaging.backend.facade.api import list_email_templates
from products.messaging.backend.facade.categories import list_categories
from products.workflows.backend.facade.contracts import SetupStep
from products.workflows.backend.facade.enums import SetupStepKey
from products.workflows.backend.models import HogFlow
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.services.data_suggestions.team_context import has_verified_email_sender
from products.workflows.backend.services.hog_flow_reads import workflow_type_q


def _frequency_cap_set(team: Team) -> bool:
    # Read without get_or_create, so checking the status never writes a config row.
    config = TeamWorkflowsConfig.objects.filter(team_id=team.id).first()
    return (
        config is not None
        and config.marketing_frequency_cap_max_messages is not None
        and config.marketing_frequency_cap_window_days is not None
    )


def email_sending_paused(team: Team) -> bool:
    # The CDP email service refuses every send in either case, so a verified domain alone is not enough.
    config = TeamWorkflowsConfig.objects.filter(team_id=team.id).first()
    return config is not None and (
        config.email_sending_suspended_at is not None or config.ses_tenant_sending_status == "DISABLED"
    )


def get_setup_steps(team: Team) -> tuple[SetupStep, ...]:
    done = {
        SetupStepKey.CHANNEL: Integration.objects.filter(team_id=team.id, kind="email").exists(),
        SetupStepKey.DOMAIN: has_verified_email_sender(team),
        SetupStepKey.OPT_OUTS: len(list_categories(team.id)) > 0,
        SetupStepKey.SENDING_RULES: _frequency_cap_set(team),
        SetupStepKey.EMAIL_TEMPLATE: len(list_email_templates(team.id, limit=1)) > 0,
        SetupStepKey.FIRST_WORKFLOW: HogFlow.objects.filter(team_id=team.id)
        .exclude(status=HogFlow.State.ARCHIVED)
        .filter(workflow_type_q({"messaging"}))
        .exists(),
    }
    return tuple(SetupStep(key=key, done=done[key]) for key in SetupStepKey)
