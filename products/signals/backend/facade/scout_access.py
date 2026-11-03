"""Who may read and write scout data, for views in signals and in other products."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from posthog.models import Team

if TYPE_CHECKING:
    from posthog.rbac.user_permissions import UserPermissions

CANONICAL_TEAM_ACCESS_DENIED_MESSAGE = "You don't have access to the project that owns this data."


def has_canonical_team_access(
    team: Team, user_permissions: "UserPermissions", scoped_team_ids: Sequence[int] | None
) -> bool:
    """Whether an authenticated caller may act on scout data for `team`.

    Scout rows canonicalize to the parent team on save. So for a child environment the caller needs
    membership of the parent team, and a credential scoped to some teams must include the parent.
    `scoped_team_ids` is None or empty when the credential has no team restriction.
    """
    if team.parent_team_id is None or team.parent_team_id == team.id or team.parent_team is None:
        return True
    if scoped_team_ids and team.parent_team_id not in scoped_team_ids:
        return False
    level = user_permissions.team(team.parent_team).effective_membership_level
    return level is not None
