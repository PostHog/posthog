from collections import defaultdict, deque
from collections.abc import Mapping
from typing import Any

from rest_framework.exceptions import ValidationError

from posthog.models.property import Property

from products.feature_flags.backend.facade.config import ConfigFormatError, detect_config_format
from products.feature_flags.backend.facade.references import flag_dependency_properties, referenced_cohort_ids


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
                    key = prop.get("key") if prop.get("type") == "flag" else ""
                    if isinstance(key, bool) or not isinstance(key, str | int):
                        raise ValueError("Invalid legacy flag dependency")
                    if prop.get("type") == "cohort":
                        try:
                            int(prop.get("value"))
                        except (TypeError, ValueError, OverflowError) as error:
                            raise ValueError("Invalid legacy flag cohort reference") from error
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


def retain_legacy_flags(
    flags: list[dict[str, Any]],
    excluded_keys: set[str] | None = None,
    flag_id_to_key: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Exclude invalid flags and their transitive dependents without modifying the input.

    Exclusions name flag keys. The ID lookup includes omitted targets so dependencies
    resolve with the transformation's ID-before-key precedence, without alias collisions.
    """
    excluded = set(excluded_keys or ())
    id_to_key = dict(flag_id_to_key or {})
    id_to_key.update(
        (str(flag["id"]), flag["key"])
        for flag in flags
        if isinstance(flag, dict) and "id" in flag and isinstance(flag.get("key"), str)
    )
    invalid_ids = {
        str(flag["id"])
        for flag in flags
        if isinstance(flag, dict) and "id" in flag and not isinstance(flag.get("key"), str)
    }
    dependents: dict[str, set[int]] = defaultdict(set)
    invalid: set[int] = set()
    for index, flag in enumerate(flags):
        try:
            if not isinstance(flag, dict) or not isinstance(flag.get("key"), str):
                raise ValueError("Invalid legacy flag definition")
            if flag["key"] in excluded:
                raise ValueError("Excluded legacy flag")
            validate_legacy_filters(flag.get("filters"))
            for prop in flag_dependency_properties(flag.get("filters")):
                reference = str(prop["key"])
                if reference in invalid_ids:
                    invalid.add(index)
                dependents[id_to_key.get(reference, reference)].add(index)
        except (AttributeError, KeyError, TypeError, ValueError):
            invalid.add(index)
    queue = deque(excluded)
    for index in invalid:
        flag = flags[index]
        if isinstance(flag, dict) and isinstance(flag.get("key"), str):
            queue.append(flag["key"])
    while queue:
        reference = queue.popleft()
        for index in dependents.get(reference, ()):
            if index not in invalid:
                invalid.add(index)
                queue.append(flags[index]["key"])
    return [flag for index, flag in enumerate(flags) if index not in invalid]


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
            value = node.get("value")
            if value is None:
                continue
            try:
                references.add(str(int(value)))
            except (TypeError, ValueError):
                continue
    return references


def validate_legacy_definitions_envelope(payload: object) -> None:
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("flags"), list)
        or not isinstance(payload.get("cohorts"), dict)
        or not isinstance(payload.get("group_type_mapping"), dict)
    ):
        raise ValueError("Invalid legacy definitions envelope")


def sanitize_legacy_definitions(
    payload: dict[str, Any],
    excluded_keys: set[str] | None = None,
    flag_id_to_key: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Remove unsafe definitions, preserving the caller's object when nothing is excluded.

    Does not mutate the input. Raises ``ValueError`` for an invalid envelope.
    """
    validate_legacy_definitions_envelope(payload)
    flags = retain_legacy_flags(payload["flags"], excluded_keys, flag_id_to_key)
    malformed_cohorts: set[str] = set()
    cohort_dependents: dict[str, set[str]] = defaultdict(set)
    cohort_dependencies: dict[str, set[str]] = {}
    for key, properties in payload["cohorts"].items():
        try:
            cohort_dependencies[key] = cohort_references(properties)
            for reference in cohort_dependencies[key]:
                cohort_dependents[reference].add(key)
        except ValueError:
            malformed_cohorts.add(key)
    pending = list(malformed_cohorts)
    while pending:
        for dependent in cohort_dependents.get(pending.pop(), ()):
            if dependent not in malformed_cohorts:
                malformed_cohorts.add(dependent)
                pending.append(dependent)
    excluded: set[str] = set()
    for flag in flags:
        if malformed_cohorts.intersection(str(cid) for cid in referenced_cohort_ids(flag.get("filters"))):
            excluded.add(flag["key"])
    if excluded:
        flags = retain_legacy_flags(payload["flags"], excluded | (excluded_keys or set()), flag_id_to_key)
    if len(flags) == len(payload["flags"]) and not malformed_cohorts:
        return payload
    reachable: set[str] = set()
    pending = [str(cid) for flag in flags for cid in referenced_cohort_ids(flag.get("filters"))]
    while pending:
        key = pending.pop()
        if key not in reachable and key not in malformed_cohorts:
            reachable.add(key)
            pending.extend(cohort_dependencies.get(key, ()))
    return {
        **payload,
        "flags": flags,
        "cohorts": {key: value for key, value in payload["cohorts"].items() if key in reachable},
    }
