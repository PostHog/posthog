from collections.abc import Iterator, Mapping
from itertools import islice

from pydantic import JsonValue

from posthog.utils import safe_int

from products.feature_flags.backend.facade.config import ConfigFormatError, detect_config_format
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def require_v1_dependency(filters: Mapping[str, JsonValue] | None) -> None:
    config_format = detect_config_format(filters)
    if config_format.kind != "v1":
        raise ConfigFormatError(config_format)


def _dependency_ids(filters: Mapping[str, JsonValue]) -> Iterator[int]:
    groups = filters.get("groups")
    if not isinstance(groups, list):
        return
    for group in groups:
        if not isinstance(group, dict):
            continue
        properties = group.get("properties")
        if not isinstance(properties, list):
            continue
        for prop in properties:
            if isinstance(prop, dict) and prop.get("type") == "flag":
                flag_id = safe_int(prop.get("key"))
                if flag_id is not None:
                    yield flag_id


def validate_dependency_formats(filters: Mapping[str, JsonValue], *, project_id: int) -> None:
    """Check formats where a write does not run the full dependency validator.

    Missing references and malformed v1 properties retain the caller's existing policy.
    Resolve IDs in project scope before inspecting any target configuration.
    """
    require_v1_dependency(filters)
    pending = set(_dependency_ids(filters))
    visited: set[int] = set()
    while pending:
        batch = set(islice(pending, 100))
        pending.difference_update(batch)
        visited.update(batch)
        for target_filters in FeatureFlag.objects.filter(id__in=batch, team__project_id=project_id).values_list(
            "filters", flat=True
        ):
            require_v1_dependency(target_filters)
            pending.update(_dependency_ids(target_filters or {}))
        pending.difference_update(visited)
