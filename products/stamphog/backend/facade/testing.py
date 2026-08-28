"""Test-support facade for stamphog.

Sibling products' tests need a repo config in a given sync state (installation bound,
connecting user set). ``facade.api.create_repo_config`` refuses that by design, because only
the verified sync flow may bind an installation, so tests seed the row here.
"""

from products.stamphog.backend.models import StamphogRepoConfig


def seed_repo_config(
    *,
    team_id: int,
    repository: str,
    enabled: bool = True,
    installation_id: str = "",
    connected_by_user_id: int | None = None,
) -> None:
    StamphogRepoConfig.objects.for_team(team_id).create(
        team_id=team_id,
        repository=repository,
        enabled=enabled,
        installation_id=installation_id,
        connected_by_user_id=connected_by_user_id,
    )
