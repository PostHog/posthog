from datetime import UTC, datetime
from typing import TYPE_CHECKING

from products.access_control.backend.facade.api import (
    every_member_has_resource_access,
    object_ids_restricted_from_any_member,
)
from products.feature_flags.backend.facade.config import served_string_values, variant_rollout_leaves_a_gap
from products.feature_flags.backend.facade.edit_history import flag_edits_since
from products.feature_flags.backend.models.feature_flag import FeatureFlag

if TYPE_CHECKING:
    from posthog.models.team import Team

MAX_FLAG_EDITS = 1000


def get_flag_property_values(team: "Team", key: str) -> list[bool | str] | None:
    flag = FeatureFlag.objects.filter(team__project_id=team.project_id, key=key).only("team_id", "filters").first()
    if flag is None or not _every_member_can_view(flag):
        return None
    current_strings = served_string_values(flag.filters)
    strings = list(dict.fromkeys([*current_strings, *_past_variant_keys(flag)]))
    if not current_strings or variant_rollout_leaves_a_gap(flag.filters):
        return [*strings, True, False]
    return [*strings, False]


def _past_variant_keys(flag: FeatureFlag) -> list[str]:
    edits = flag_edits_since(
        team_id=flag.team_id, feature_flag_id=flag.id, since=datetime.min.replace(tzinfo=UTC), limit=MAX_FLAG_EDITS
    )
    return [
        variant["key"]
        for edit in edits
        for variants in (edit.before.variants, edit.after.variants)
        if isinstance(variants, list)
        for variant in variants
        if isinstance(variant, dict) and variant.get("key")
    ]


def _every_member_can_view(flag: FeatureFlag) -> bool:
    if not every_member_has_resource_access(team_id=flag.team_id, resource="feature_flag", required_level="viewer"):
        return False
    restricted = object_ids_restricted_from_any_member(
        team_id=flag.team_id, resource="feature_flag", required_level="viewer"
    )
    return str(flag.id) not in restricted
