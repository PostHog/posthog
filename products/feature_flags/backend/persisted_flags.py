from collections.abc import Iterable
from typing import Any

FlagDefinition = dict[str, Any]


def is_unconditionally_fully_rolled_out(flag: FlagDefinition) -> bool:
    if not flag.get("active", False) or flag.get("deleted", False):
        return False

    filters = flag.get("filters") or {}

    multivariate = filters.get("multivariate") or {}
    if multivariate.get("variants"):
        return False
    if filters.get("holdout"):
        return False
    if filters.get("super_groups"):
        return False
    if filters.get("aggregation_group_type_index") is not None:
        return False

    groups = filters.get("groups") or []
    if len(groups) != 1:
        return False

    group = groups[0]
    if group.get("properties"):
        return False
    if group.get("variant"):
        return False

    rollout_percentage = group.get("rollout_percentage")
    return rollout_percentage is None or rollout_percentage == 100


def get_dynamic_persisted_feature_flags(
    definitions: list[FlagDefinition] | None,
    static_keys: Iterable[str] = (),
) -> list[str]:
    keys = set(static_keys)
    for flag in definitions or []:
        key = flag.get("key")
        if key and is_unconditionally_fully_rolled_out(flag):
            keys.add(key)
    return sorted(keys)
