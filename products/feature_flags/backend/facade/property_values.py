from typing import TYPE_CHECKING

from products.access_control.backend.facade.api import (
    every_member_has_resource_access,
    object_ids_restricted_from_any_member,
)
from products.feature_flags.backend.facade.config import served_string_values, variant_rollout_leaves_a_gap
from products.feature_flags.backend.models.feature_flag import FeatureFlag

if TYPE_CHECKING:
    from posthog.models.team import Team


def get_flag_property_values(team: "Team", key: str) -> list[bool | str] | None:
    flag = FeatureFlag.objects.filter(team__project_id=team.project_id, key=key).only("team_id", "filters").first()
    if flag is None or not _every_member_can_view(flag):
        return None
    strings = served_string_values(flag.filters)
    if not strings or variant_rollout_leaves_a_gap(flag.filters):
        return [*strings, True, False]
    return [*strings, False]


def _every_member_can_view(flag: FeatureFlag) -> bool:
    if not every_member_has_resource_access(team_id=flag.team_id, resource="feature_flag", required_level="viewer"):
        return False
    restricted = object_ids_restricted_from_any_member(
        team_id=flag.team_id, resource="feature_flag", required_level="viewer"
    )
    return str(flag.id) not in restricted
