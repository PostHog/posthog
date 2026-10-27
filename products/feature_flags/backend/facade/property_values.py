from typing import TYPE_CHECKING

from products.access_control.backend.facade.api import (
    every_member_has_resource_access,
    object_ids_restricted_from_any_member,
)
from products.feature_flags.backend.facade.config import served_string_values
from products.feature_flags.backend.facade.edit_history import served_strings_in_edits
from products.feature_flags.backend.models.feature_flag import FeatureFlag

if TYPE_CHECKING:
    from posthog.models.team import Team


def flag_property_values_revision(team: "Team", key: str) -> str | None:
    visible = _visible_flag(team, key)
    if visible is None:
        return None
    flag, hidden_flag_ids = visible
    return f"{flag.id}:{flag.updated_at}:{','.join(sorted(hidden_flag_ids))}"


def get_flag_property_values(team: "Team", key: str) -> list[bool | str] | None:
    visible = _visible_flag(team, key)
    if visible is None:
        return None
    flag, hidden_flag_ids = visible
    strings = [
        *served_string_values(flag.filters),
        *served_strings_in_edits(team_id=flag.team_id, flag_key=key, excluded_flag_ids=hidden_flag_ids),
    ]
    values: list[bool | str] = [*dict.fromkeys(strings), True, False]
    return values


def _visible_flag(team: "Team", key: str) -> tuple[FeatureFlag, set[str]] | None:
    flag = (
        FeatureFlag.objects_including_soft_deleted.filter(team__project_id=team.project_id, key=key)
        .order_by("deleted")
        .only("team_id", "filters", "updated_at")
        .first()
    )
    if flag is None or not every_member_has_resource_access(
        team_id=flag.team_id, resource="feature_flag", required_level="viewer"
    ):
        return None
    hidden_flag_ids = object_ids_restricted_from_any_member(
        team_id=flag.team_id, resource="feature_flag", required_level="viewer"
    )
    if str(flag.id) in hidden_flag_ids:
        return None
    return flag, hidden_flag_ids
