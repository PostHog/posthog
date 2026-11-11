from typing import TYPE_CHECKING

from products.access_control.backend.facade.api import (
    every_member_has_resource_access,
    object_ids_restricted_from_any_member,
)
from products.feature_flags.backend.facade.config import served_holdout_values, served_string_values
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
        *served_holdout_values(flag.filters),
        *served_strings_in_edits(team_id=flag.team_id, flag_key=key, excluded_flag_ids=hidden_flag_ids),
    ]
    values: list[bool | str] = [*strings, True, False]
    return values


def _visible_flag(team: "Team", key: str) -> tuple[FeatureFlag, set[str]] | None:
    flag = _find_flag(team, key)
    # Suggestions are cached per team, not per user, so a flag hidden from any member is never served.
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


def _find_flag(team: "Team", key: str) -> FeatureFlag | None:
    # `filters` stays deferred, so the cache revision never loads it and values load it once on a cache miss.
    flags = FeatureFlag.objects_including_soft_deleted.filter(team__project_id=team.project_id).only(
        "team_id", "key", "deleted", "updated_at"
    )
    flag = flags.filter(key=key).order_by("deleted").first()
    if flag is not None:
        return flag
    tombstoned = flags.filter(deleted=True, key__startswith=f"{key}:deleted:")
    return next((flag for flag in tombstoned if flag.key_without_tombstone() == key), None)
