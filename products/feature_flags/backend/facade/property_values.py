from typing import TYPE_CHECKING

from products.access_control.backend.facade.api import (
    every_member_has_resource_access,
    object_ids_restricted_from_any_member,
)
from products.feature_flags.backend.facade.config import served_string_values
from products.feature_flags.backend.facade.edit_history import variant_keys_in_edits
from products.feature_flags.backend.models.feature_flag import FeatureFlag

if TYPE_CHECKING:
    from posthog.models.team import Team


def get_flag_property_values(team: "Team", key: str) -> list[bool | str] | None:
    flag = (
        FeatureFlag.objects_including_soft_deleted.filter(team__project_id=team.project_id, key=key)
        .order_by("deleted")
        .only("team_id", "filters")
        .first()
    )
    if flag is None or not _every_member_can_view(flag):
        return None
    strings = [*served_string_values(flag.filters), *variant_keys_in_edits(team_id=flag.team_id, flag_key=key)]
    values: list[bool | str] = [*dict.fromkeys(strings), True, False]
    return values


def _every_member_can_view(flag: FeatureFlag) -> bool:
    if not every_member_has_resource_access(team_id=flag.team_id, resource="feature_flag", required_level="viewer"):
        return False
    restricted = object_ids_restricted_from_any_member(
        team_id=flag.team_id, resource="feature_flag", required_level="viewer"
    )
    return str(flag.id) not in restricted
