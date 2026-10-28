from products.integrations.backend.facade.api import IntegrationManager, IntegrationRecord
from products.integrations.backend.facade.contracts import IntegrationNotFound

# Slack webhooks carry the workspace id and no team, so these reads scope rows by the workspace id.


def workspace_integrations(slack_team_id: str) -> list[IntegrationRecord]:
    """The Slack app rows of a workspace, one per linked project, oldest id first."""
    rows = IntegrationManager.slack.oauth.list_by_external_id(slack_team_id)
    return sorted(rows, key=lambda row: row.id)


def get_workspace_integration(integration_id: object, slack_team_id: str) -> IntegrationRecord | None:
    """The Slack app row with this id in the workspace, or None when the id is unknown or invalid."""
    if isinstance(integration_id, bool) or not isinstance(integration_id, int | str):
        return None
    try:
        wanted = int(integration_id)
    except ValueError:
        return None
    return next((row for row in workspace_integrations(slack_team_id) if row.id == wanted), None)


def workspace_integration_exists(integration_id: object, slack_team_id: str) -> bool:
    return get_workspace_integration(integration_id, slack_team_id) is not None


def get_team_workspace_integration(team_id: int, slack_team_id: str) -> IntegrationRecord | None:
    """The Slack app row that links this workspace to this project, or None."""
    return IntegrationManager.slack.oauth.find(team_id, external_id=slack_team_id)


def require_workspace_integration(integration_id: object, slack_team_id: str) -> IntegrationRecord:
    """Like `get_workspace_integration`, but raises `IntegrationNotFound` so a Temporal activity retries."""
    row = get_workspace_integration(integration_id, slack_team_id)
    if row is None:
        raise IntegrationNotFound(f"No Slack integration {integration_id!r} in workspace {slack_team_id!r}")
    return row
