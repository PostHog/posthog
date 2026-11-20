"""The work of the foreign keys to integration rows and of the integration delete receiver. The integrations SDK loads this module."""

from posthog.integrations import IntegrationRecord

from products.tasks.backend.models import (
    Channel,
    SandboxSnapshot,
    Task,
    clear_channel_repositories_of_github_integration,
)


def before_integration_delete(row: IntegrationRecord) -> None:
    if row.kind == "github":
        clear_channel_repositories_of_github_integration(row.team_id, row.id)
    # SET_NULL foreign keys.
    Channel.objects.for_team(row.team_id).filter(github_integration_id=row.id).update(github_integration=None)
    Task.objects.filter(team_id=row.team_id, github_integration_id=row.id).update(github_integration=None)
    SandboxSnapshot.objects.filter(integration_id=row.id).update(integration=None)
