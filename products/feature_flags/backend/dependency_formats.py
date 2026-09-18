from collections.abc import Iterator, Mapping
from itertools import islice

from pydantic import JsonValue

from posthog.utils import safe_int

from products.feature_flags.backend.facade.config import ConfigFormatError, detect_config_format
from products.feature_flags.backend.models.feature_flag import FeatureFlag

DEPENDENCY_BATCH_SIZE = 100


class DependencyConfigFormatError(ConfigFormatError):
    def __init__(self, error: ConfigFormatError, *, flag_id: int) -> None:
        super().__init__(error.config_format)
        self.flag_id = flag_id


def require_v1_config(filters: Mapping[str, JsonValue] | None) -> None:
    config_format = detect_config_format(filters)
    if config_format.kind != "v1":
        raise ConfigFormatError(config_format)


def _dependency_ids(filters: Mapping[str, JsonValue]) -> Iterator[int]:
    # Unlike facade.references.flag_dependency_properties, this walk skips malformed
    # stored groups and properties so format checks do not change their validation policy.
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
    """Check formats for group-only conditions and writes that enable or restore a flag without filters.

    Skip dependency IDs with no matching row in the project and properties that are not
    v1 flag references. The calling write path decides how to handle those cases.
    Resolve IDs in project scope before inspecting any target configuration.
    """
    require_v1_config(filters)
    pending = set(_dependency_ids(filters))
    visited: set[int] = set()
    while pending:
        batch = set(islice(pending, DEPENDENCY_BATCH_SIZE))
        pending.difference_update(batch)
        visited.update(batch)
        for target_id, target_filters in FeatureFlag.objects.filter(
            id__in=batch, team__project_id=project_id
        ).values_list("id", "filters"):
            try:
                require_v1_config(target_filters)
            except ConfigFormatError as exc:
                raise DependencyConfigFormatError(exc, flag_id=target_id) from exc
            pending.update(_dependency_ids(target_filters or {}))
        pending.difference_update(visited)
