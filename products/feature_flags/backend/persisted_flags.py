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
    # Early access enrollment, in its legacy (`super_groups`) and current (`feature_enrollment`)
    # encodings, lets a person opt out of a fully rolled-out flag. The frontend merges persisted
    # flags under the client's flags, and posthog-js omits disabled flags, so persisting such a
    # flag would turn it back on for a person who opted out.
    if filters.get("super_groups") or filters.get("feature_enrollment"):
        return False
    if filters.get("aggregation_group_type_index") is not None:
        return False

    # Release-condition groups are OR-ed: a single blanket group (no properties,
    # 100%-or-unset rollout, no variant override) means everyone matches, regardless
    # of the other, more targeted groups alongside it.
    for group in filters.get("groups") or []:
        if group.get("properties"):
            continue
        if group.get("variant"):
            continue
        rollout_percentage = group.get("rollout_percentage")
        if rollout_percentage is None or rollout_percentage == 100:
            return True

    return False


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
