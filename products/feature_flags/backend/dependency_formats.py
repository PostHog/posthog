from collections.abc import Iterator, Mapping
from typing import Any

from posthog.utils import safe_int

from products.feature_flags.backend.facade.config import ConfigFormatError, detect_config_format
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def require_v1_dependency(filters: Mapping[str, Any] | None) -> None:
    config_format = detect_config_format(filters)
    if config_format.kind != "v1":
        raise ConfigFormatError(config_format)


def _dependency_ids(filters: Mapping[str, Any]) -> Iterator[int]:
    groups = filters.get("groups")
    if not isinstance(groups, list):
        return
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("properties"), list):
            continue
        for prop in group["properties"]:
            if isinstance(prop, dict) and prop.get("type") == "flag":
                flag_id = safe_int(prop.get("key"))
                if flag_id is not None:
                    yield flag_id


def validate_dependency_formats(filters: Mapping[str, Any], *, project_id: int) -> None:
    """Check formats where a write does not run the full dependency validator.

    Missing references and malformed v1 properties retain the caller's existing policy.
    Resolve IDs in project scope before inspecting any target configuration.
    """
    pending = [filters]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        require_v1_dependency(current)
        for flag_id in _dependency_ids(current):
            if flag_id in visited:
                continue
            visited.add(flag_id)
            flag = FeatureFlag.objects.filter(id=flag_id, team__project_id=project_id).first()
            if flag is not None:
                require_v1_dependency(flag.filters)
                pending.append(flag.filters or {})
