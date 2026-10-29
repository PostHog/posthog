from copy import deepcopy
from typing import TYPE_CHECKING, cast

from pydantic import JsonValue
from rest_framework.exceptions import PermissionDenied

from posthog.hogql.restricted_properties import restricted_feature_flag_names

from posthog.constants import GROUP_TYPES_LIMIT
from posthog.models.group_type_mapping import get_group_types_for_project

if TYPE_CHECKING:
    from posthog.models import Team

FEATURE_FLAG_PREFIX = "$feature/"
FEATURE_FLAG_MAPS = ("$active_feature_flags", "$feature_flags")


class MCPEventPropertyAccess:
    @staticmethod
    def _paths_overlap(name: str, key: str) -> bool:
        return name == key or name.startswith(key + ".") or key.startswith(name + ".")

    @classmethod
    def with_group_aliases(cls, restricted_names: set[str], *, team: "Team") -> set[str]:
        keys = {key.replace("%2E", ".") for key in restricted_names}
        indexed = {f"$group_{index}" for index in range(GROUP_TYPES_LIMIT)}
        if not any(cls._paths_overlap(key, "$groups") or key in indexed for key in keys):
            return keys
        group_types = {
            mapping["group_type_index"]: mapping["group_type"]
            for mapping in get_group_types_for_project(team.project_id)
        }
        expanded = keys.copy()
        for index in range(GROUP_TYPES_LIMIT):
            alias = f"$group_{index}"
            group_type = group_types.get(index)
            canonical = (f"$groups.{group_type}" if group_type is not None else "$groups").replace("%2E", ".")
            if any(cls._paths_overlap(key, canonical) for key in keys):
                expanded.add(alias)
            if any(cls._paths_overlap(key, alias) for key in keys):
                expanded.update({alias, canonical})
        return expanded

    @classmethod
    def validate(cls, name: str | None, restricted_names: set[str]) -> None:
        if not restricted_names:
            return
        if name is None:
            raise PermissionDenied("The filter reads a properties object your account cannot fully access.")
        name = name.replace("%2E", ".")
        keys = {key.replace("%2E", ".") for key in restricted_names}
        if "$feature_flags" in keys and (
            name.startswith(FEATURE_FLAG_PREFIX) or name.split(".")[0] in FEATURE_FLAG_MAPS
        ):
            raise PermissionDenied("The filter reads feature flags your account cannot fully access.")
        if any(cls._paths_overlap(name, key) for key in keys):
            raise PermissionDenied("The filter uses a property your account cannot read.")
        if restricted_feature_flag_names(keys) and name.split(".")[0] in FEATURE_FLAG_MAPS:
            raise PermissionDenied("The filter reads feature flags your account cannot fully access.")

    @staticmethod
    def redaction(restricted_names: list[str]) -> dict[str, JsonValue]:
        """The rules the destination's Hog applies to `data.properties`.

        Hog cannot walk arbitrary paths, so a restriction deeper than one nested key, or a nested restriction on a
        value of an unexpected type, drops the whole top-level property.
        """
        keys: set[str] = set()
        prefixes: set[str] = set()
        children: dict[str, set[str]] = {}
        items: dict[str, set[str]] = {}
        for raw_name in restricted_names:
            name = raw_name.replace("%2E", ".")
            keys.update({raw_name, name})
            prefixes.update({f"{name}.", f"{raw_name}%2E"})
            parent, _, child = name.partition(".")
            if child and "." not in child:
                children.setdefault(parent, set()).add(child)
            elif child:
                keys.add(parent)
        if "$feature_flags" in keys:
            keys.update(FEATURE_FLAG_MAPS)
            prefixes.add(FEATURE_FLAG_PREFIX)
        for flag in restricted_feature_flag_names(keys):
            children.setdefault("$feature_flags", set()).add(flag)
            items.setdefault("$active_feature_flags", set()).add(flag)
        rules: dict[str, JsonValue] = {
            "names": list[JsonValue](sorted(keys)),
            "prefixes": list[JsonValue](sorted(prefixes)),
            "children": {parent: list[JsonValue](sorted(names)) for parent, names in sorted(children.items())},
            "items": {parent: list[JsonValue](sorted(names)) for parent, names in sorted(items.items())},
        }
        return rules

    @staticmethod
    def redact(properties: dict[str, JsonValue], redaction: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Python twin of the destination's Hog redaction, for previews."""
        keys = cast(list[str], redaction["names"])
        prefixes = cast(list[str], redaction["prefixes"])
        children = cast(dict[str, list[str]], redaction["children"])
        items = cast(dict[str, list[str]], redaction["items"])
        result: dict[str, JsonValue] = {}
        for key, value in properties.items():
            if key in keys or any(key.startswith(prefix) for prefix in prefixes):
                continue
            if key in children:
                if isinstance(value, dict):
                    result[key] = {
                        child: deepcopy(item)
                        for child, item in value.items()
                        if not any(
                            MCPEventPropertyAccess._paths_overlap(child.replace("%2E", "."), hidden)
                            for hidden in children[key]
                        )
                    }
            elif key in items:
                if isinstance(value, list):
                    result[key] = [deepcopy(item) for item in value if item not in items[key]]
            else:
                result[key] = deepcopy(value)
        return result
