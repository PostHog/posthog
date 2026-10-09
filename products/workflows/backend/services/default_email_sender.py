"""The project's default email sender, which new broadcasts and workflow email steps start with."""

from posthog.models.team import Team

from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.services.email_sending_controls import ensure_workflows_config


def _forget_memoized_config() -> None:
    # Team.workflows_config is memoized for the whole process, so a write that bypasses the
    # memoized row would keep serving the old sender to this team's next request.
    Team.workflows_config.fget.cache_clear()  # type: ignore[attr-defined]


def set_default_email_sender_if_unset(team_id: int, integration_id: int) -> bool:
    ensure_workflows_config(team_id)
    updated = TeamWorkflowsConfig.objects.filter(team_id=team_id, default_email_integration_id__isnull=True).update(
        default_email_integration_id=integration_id
    )
    if updated:
        _forget_memoized_config()
    return updated > 0


def clear_default_email_sender(team_id: int, integration_id: int) -> None:
    cleared = TeamWorkflowsConfig.objects.filter(team_id=team_id, default_email_integration_id=integration_id).update(
        default_email_integration_id=None
    )
    if cleared:
        _forget_memoized_config()
