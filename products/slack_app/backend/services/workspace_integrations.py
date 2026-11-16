from collections.abc import Iterable
from typing import Protocol, cast

from django.db.models import Model, prefetch_related_objects

from posthog.integrations import IntegrationManager, IntegrationNotFound, IntegrationRecord
from posthog.models.team import Team

# Slack webhooks carry the workspace id and no team, so these reads scope rows by the workspace id.


class WorkspaceIntegration(IntegrationRecord, Protocol):
    """A Slack row with its team and organization loaded. Only `with_teams` makes one."""

    @property
    def integration_id(self) -> str: ...

    @property
    def team(self) -> Team: ...


def with_teams(rows: Iterable[IntegrationRecord]) -> list[WorkspaceIntegration]:
    """Load the team and organization of all rows in two queries, because callers read `row.team.organization`."""
    loaded = list(rows)
    prefetch_related_objects(cast(list[Model], loaded), "team__organization")
    # The prefetch above makes this true at runtime. A frozen record can replace it with a team lookup here.
    return cast(list[WorkspaceIntegration], loaded)


def workspace_integrations(slack_team_id: str) -> list[WorkspaceIntegration]:
    """The Slack app rows of a workspace, one per linked project, oldest id first."""
    rows = IntegrationManager.slack.oauth.list_by_external_id(slack_team_id)
    return with_teams(sorted(rows, key=lambda row: row.id))


def _fetch_workspace_integration(integration_id: object, slack_team_id: str) -> IntegrationRecord | None:
    if isinstance(integration_id, bool) or not isinstance(integration_id, int | str):
        return None
    try:
        wanted = int(integration_id)
    except ValueError:
        return None
    try:
        return IntegrationManager.slack.oauth.get_by_external_id(slack_team_id, wanted)
    except IntegrationNotFound:
        return None


def get_workspace_integration(integration_id: object, slack_team_id: str) -> WorkspaceIntegration | None:
    """The Slack app row with this id in the workspace, or None when the id is unknown or invalid."""
    row = _fetch_workspace_integration(integration_id, slack_team_id)
    return None if row is None else with_teams([row])[0]


def workspace_integration_exists(integration_id: object, slack_team_id: str) -> bool:
    return _fetch_workspace_integration(integration_id, slack_team_id) is not None


def get_team_workspace_integration(team_id: int, slack_team_id: str) -> WorkspaceIntegration | None:
    """The Slack app row that links this workspace to this project, or None."""
    row = IntegrationManager.slack.oauth.find(team_id, external_id=slack_team_id)
    return None if row is None else with_teams([row])[0]


def require_workspace_integration(integration_id: object, slack_team_id: str) -> WorkspaceIntegration:
    """Like `get_workspace_integration`, but raises `IntegrationNotFound` so a Temporal activity retries."""
    row = get_workspace_integration(integration_id, slack_team_id)
    if row is None:
        raise IntegrationNotFound(f"No Slack integration {integration_id!r} in workspace {slack_team_id!r}")
    return row
