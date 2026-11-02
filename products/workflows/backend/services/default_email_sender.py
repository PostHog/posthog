"""The project's default email sender, which new broadcasts and workflow email steps start with."""

from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.services.email_sending_controls import ensure_workflows_config


def set_default_email_sender_if_unset(team_id: int, integration_id: int) -> bool:
    ensure_workflows_config(team_id)
    updated = TeamWorkflowsConfig.objects.filter(team_id=team_id, default_email_integration_id__isnull=True).update(
        default_email_integration_id=integration_id
    )
    return updated > 0


def clear_default_email_sender(team_id: int, integration_id: int) -> None:
    TeamWorkflowsConfig.objects.filter(team_id=team_id, default_email_integration_id=integration_id).update(
        default_email_integration_id=None
    )
