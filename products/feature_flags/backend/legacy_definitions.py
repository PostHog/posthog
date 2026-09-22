from collections import defaultdict, deque
from collections.abc import Mapping
from typing import Any

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
                    if prop.get("type") == "flag" and not isinstance(prop.get("key"), str):
                        raise ValueError("Invalid legacy flag dependency")
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
    flags: list[dict[str, Any]], excluded_references: set[str] | None = None
) -> list[dict[str, Any]]:
    """Exclude invalid flags and their transitive dependents without modifying the input.

    Seed ``excluded_references`` with both the string id and key of each excluded
    flag, because dependencies can use either. Seeds exclude dependents only;
    callers must remove the seeded flags themselves if they are still in ``flags``.
    """
    excluded = set(excluded_references or ())
    dependents: dict[str, set[int]] = defaultdict(set)
    invalid: set[int] = set()
    for index, flag in enumerate(flags):
        try:
            if not isinstance(flag, dict) or not isinstance(flag.get("key"), str):
                raise ValueError("Invalid legacy flag definition")
            validate_legacy_filters(flag.get("filters"))
            for prop in flag_dependency_properties(flag.get("filters")):
                dependents[prop["key"]].add(index)
        except (AttributeError, KeyError, TypeError, ValueError):
            invalid.add(index)
    queue = deque(excluded)
    for index in invalid:
        flag = flags[index]
        if isinstance(flag, dict):
            queue.extend(str(flag[field]) for field in ("id", "key") if field in flag)
    while queue:
        reference = queue.popleft()
        for index in dependents.get(reference, ()):
            if index not in invalid:
                invalid.add(index)
                flag = flags[index]
                queue.extend(str(flag[field]) for field in ("id", "key") if field in flag)
    return [flag for index, flag in enumerate(flags) if index not in invalid]


def cohort_references(properties: object) -> set[str]:
    references: set[str] = set()
    pending = [properties]
    while pending:
        node = pending.pop()
        if not isinstance(node, dict):
            raise ValueError("Invalid legacy cohort properties")
        if "values" in node:
            values = node["values"]
            if not isinstance(values, list):
                raise ValueError("Invalid legacy cohort group")
            pending.extend(values)
        elif node.get("type") == "cohort":
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


def sanitize_legacy_definitions(payload: dict[str, Any], excluded_references: set[str] | None = None) -> dict[str, Any]:
    """Remove unsafe definitions, preserving the caller's object when nothing is excluded.

    Does not mutate the input. Raises ``ValueError`` for an invalid envelope.
    ``excluded_references`` follows ``retain_legacy_flags``: include both the
    string id and key of each excluded flag so either reference excludes dependents.
    """
    validate_legacy_definitions_envelope(payload)
    flags = retain_legacy_flags(payload["flags"], excluded_references)
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
            excluded.update(str(flag[field]) for field in ("id", "key") if field in flag)
    if excluded:
        # Seeds exclude dependents, so remove the flags with malformed cohorts first.
        flags = [flag for flag in flags if flag["key"] not in excluded]
        flags = retain_legacy_flags(flags, excluded)
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
