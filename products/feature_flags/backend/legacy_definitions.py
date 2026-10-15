from collections import defaultdict, deque
from collections.abc import Mapping
from typing import Any

from rest_framework.exceptions import ValidationError

from posthog.models.property import Property

from products.feature_flags.backend.facade.config import ConfigFormatError, detect_config_format
from products.feature_flags.backend.facade.references import flag_dependency_properties


def _parse_cohort_reference(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise ValueError("Invalid legacy cohort reference")
    return int(value)


def validate_legacy_filters(filters: object) -> None:
    if filters is not None and not isinstance(filters, Mapping):
        raise ValueError("Invalid legacy flag filters")
    config_format = detect_config_format(filters)
    if config_format.kind != "v1":
        raise ConfigFormatError(config_format)
    if filters is None:
        return
    groups = filters.get("groups")
    if groups is not None:
        if not isinstance(groups, list):
            raise ValueError("Invalid legacy flag groups")
        for group in groups:
            if not isinstance(group, dict):
                raise ValueError("Invalid legacy flag group")
            properties = group.get("properties")
            if properties is not None:
                if not isinstance(properties, list) or any(not isinstance(prop, dict) for prop in properties):
                    raise ValueError("Invalid legacy flag properties")
                for prop in properties:
                    if prop.get("type") == "flag":
                        key = prop.get("key")
                        if isinstance(key, bool) or not isinstance(key, str | int):
                            raise ValueError("Invalid legacy flag dependency")
                    elif prop.get("type") == "cohort":
                        _parse_cohort_reference(prop.get("value"))
    for field in ("payloads", "holdout"):
        if filters.get(field) is not None and not isinstance(filters[field], dict):
            raise ValueError("Invalid legacy flag configuration")
    multivariate = filters.get("multivariate")
    if multivariate is not None:
        if not isinstance(multivariate, dict):
            raise ValueError("Invalid legacy flag variants")
        variants = multivariate.get("variants")
        if variants is not None and (
            not isinstance(variants, list) or any(not isinstance(variant, dict) for variant in variants)
        ):
            raise ValueError("Invalid legacy flag variants")


def drop_legacy_dependents(flags: list[dict[str, Any]], excluded: Mapping[str, str]) -> list[dict[str, Any]]:
    """Drop flags that depend, directly or transitively, on an excluded flag, without modifying the input.

    ``excluded`` maps each excluded flag's ID to its key. The ID lookup also covers these
    flags, which are already left out of ``flags``, so a dependency written as an ID
    resolves to that flag's key before it is treated as a key. A flag whose key is "7"
    is then not mistaken for the flag with ID 7.
    """
    if not excluded:
        return flags
    id_to_key = {**excluded, **{str(flag["id"]): flag["key"] for flag in flags}}
    dependents: dict[str, set[int]] = defaultdict(set)
    for index, flag in enumerate(flags):
        for prop in flag_dependency_properties(flag["filters"]):
            reference = str(prop["key"])
            dependents[id_to_key.get(reference, reference)].add(index)
    dropped: set[int] = set()
    queue = deque(excluded.values())
    while queue:
        for index in dependents.get(queue.popleft(), ()):
            if index not in dropped:
                dropped.add(index)
                queue.append(flags[index]["key"])
    return [flag for index, flag in enumerate(flags) if index not in dropped]


def cohort_references(properties: object) -> set[str]:
    references: set[str] = set()
    pending = [properties]
    while pending:
        node = pending.pop()
        if not isinstance(node, dict):
            raise ValueError("Invalid legacy cohort properties")
        if not node:
            continue
        if "values" in node:
            values = node["values"]
            group_type = node.get("type")
            if (
                not isinstance(values, list)
                or not isinstance(group_type, str)
                or group_type.upper() not in ("AND", "OR")
            ):
                raise ValueError("Invalid legacy cohort group")
            pending.extend(values)
            continue
        try:
            # Filter silently drops properties that fail construction.
            Property(**node)
        except (TypeError, ValueError, ValidationError) as error:
            raise ValueError("Invalid legacy cohort property") from error
        if node.get("type") == "cohort":
            references.add(str(_parse_cohort_reference(node.get("value"))))
    return references
