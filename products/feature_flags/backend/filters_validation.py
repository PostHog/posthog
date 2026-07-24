"""Cross-field validation for the `FeatureFlag.filters` JSON (issue #50084, cross-field tier).

The structural tier (`api/filters_schema.py`) checks shape and types; this module checks
invariants between fields: variant sums, key uniqueness, payload/variant agreement, and
operator/value compatibility. Contextual checks (cohort existence, circular dependencies,
size limits, feature gates) need DB or request state and stay in
`FeatureFlagSerializer.validate_filters`.

Every check takes a filters dict that already passed `FeatureFlagFiltersSerializer` — types
are trusted, operators are canonical (aliases applied), payload values are JSON-encoded
strings — and returns violations instead of raising, so the `audit_flag_filters` management
command can report all of them per flag. `validate_cross_field_or_raise` is the fail-fast
wrapper for the write path (wired in a later phase).
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail
from rest_framework.settings import api_settings

from posthog.hogql.property import parse_semver

from posthog.models.property.property import STRING_PREFIX_SUFFIX_OPERATORS
from posthog.queries.base import determine_parsed_date_for_property_matching

from products.feature_flags.backend.api.filters_schema import FeatureFlagFiltersSerializer

DATE_OPERATORS: frozenset[str] = frozenset({"is_date_exact", "is_date_after", "is_date_before"})
STRING_VALUE_OPERATORS: frozenset[str] = frozenset(
    {
        "regex",
        "not_regex",
        "icontains",
        "not_icontains",
        "gt",
        "gte",
        "lt",
        "lte",
    }
    | set(STRING_PREFIX_SUFFIX_OPERATORS)
)
LIST_VALUE_OPERATORS: frozenset[str] = frozenset({"icontains_multi", "not_icontains_multi"})
SEMVER_OPERATORS: frozenset[str] = frozenset(
    {
        "semver_gt",
        "semver_gte",
        "semver_lt",
        "semver_lte",
        "semver_eq",
        "semver_neq",
        "semver_tilde",
        "semver_caret",
        "semver_wildcard",
    }
)
PERSON_AGGREGATED_PROPERTY_TYPES: tuple[str, ...] = ("person", "cohort", "flag")


@dataclass(frozen=True)
class Violation:
    rule_id: str  # stable grouping key, index-free (e.g. "cross_field.variant_rollout_sum_not_100")
    path: str  # concrete location, indices preserved (e.g. "groups[2].properties[0].value")
    message: str


def _variant_keys(filters: Mapping[str, Any]) -> set[str]:
    return {variant["key"] for variant in (filters.get("multivariate") or {}).get("variants", [])}


def check_variant_rollout_sum(filters: Mapping[str, Any]) -> list[Violation]:
    variant_list = (filters.get("multivariate") or {}).get("variants", [])
    if not variant_list:
        return []
    # Exact equality is deliberate parity with the live write path, which enforces
    # `sum != 100`. Float summation is deterministic, so any flag that passed that check at
    # write time still sums to exactly 100 here; near-100 drift only exists on rows that
    # predate the check, and those genuinely need cleanup before enforcement because the
    # write path would reject them on their next update anyway.
    rollout_sum = sum(variant.get("rollout_percentage", 0) for variant in variant_list)
    if rollout_sum != 100:
        return [
            Violation(
                rule_id="cross_field.variant_rollout_sum_not_100",
                path="multivariate.variants",
                message=f"Variant rollout percentages must sum to 100, got {rollout_sum}.",
            )
        ]
    return []


def check_variant_keys_unique(filters: Mapping[str, Any]) -> list[Violation]:
    variant_list = (filters.get("multivariate") or {}).get("variants", [])
    seen: set[str] = set()
    duplicates: set[str] = set()
    for variant in variant_list:
        key = variant["key"]
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    if duplicates:
        return [
            Violation(
                rule_id="cross_field.variant_keys_not_unique",
                path="multivariate.variants",
                message=f"Variant keys must be unique, duplicated: {', '.join(sorted(duplicates))}.",
            )
        ]
    return []


def check_payload_keys(filters: Mapping[str, Any]) -> list[Violation]:
    payloads = filters.get("payloads") or {}
    if not payloads:
        return []
    if filters.get("multivariate"):
        variant_keys = _variant_keys(filters)
        return [
            Violation(
                rule_id="cross_field.payload_key_not_a_variant",
                path=f"payloads.{key}",
                message=f"Payload key '{key}' does not match any variant key.",
            )
            for key in payloads
            if key not in variant_keys
        ]
    return [
        Violation(
            rule_id="cross_field.payload_key_not_true",
            path=f"payloads.{key}",
            message=f"Payload key '{key}' is invalid: boolean flags only support the 'true' key.",
        )
        for key in payloads
        if key != "true"
    ]


def check_group_variant_references(filters: Mapping[str, Any]) -> list[Violation]:
    variant_keys = _variant_keys(filters)
    violations = []
    for group_index, group in enumerate(filters.get("groups", [])):
        variant = group.get("variant")
        if variant and variant not in variant_keys:
            violations.append(
                Violation(
                    rule_id="cross_field.group_variant_not_a_variant",
                    path=f"groups[{group_index}].variant",
                    message=f"Variant override '{variant}' does not match any variant key.",
                )
            )
    return violations


def check_property_types_match_aggregation(filters: Mapping[str, Any]) -> list[Violation]:
    violations = []
    flag_level_aggregation = filters.get("aggregation_group_type_index")
    for group_index, group in enumerate(filters.get("groups", [])):
        # An absent key falls back to the flag-level aggregation; an explicit null means person
        # aggregation. Stored legacy flags predate per-group aggregation, so skipping the
        # fallback would misfire on every one of them.
        aggregation = (
            group["aggregation_group_type_index"] if "aggregation_group_type_index" in group else flag_level_aggregation
        )
        for prop_index, prop in enumerate(group.get("properties", [])):
            path = f"groups[{group_index}].properties[{prop_index}]"
            if aggregation is None:
                if prop.get("type") not in PERSON_AGGREGATED_PROPERTY_TYPES:
                    violations.append(
                        Violation(
                            rule_id="cross_field.person_aggregation_property_type",
                            path=path,
                            message="Person-aggregated conditions can only use person, cohort, and flag properties.",
                        )
                    )
            elif prop.get("type") != "group":
                violations.append(
                    Violation(
                        rule_id="cross_field.group_aggregation_property_type",
                        path=path,
                        message="Group-aggregated conditions can only use group properties.",
                    )
                )
            elif prop.get("group_type_index") != aggregation:
                violations.append(
                    Violation(
                        rule_id="cross_field.group_property_type_index_mismatch",
                        path=path,
                        message="Group properties must match the condition set's group type.",
                    )
                )
    return violations


def _check_semver_value(value: Any, operator: str, path: str) -> Violation | None:
    if not isinstance(value, str):
        return Violation(
            rule_id="cross_field.semver_value_invalid",
            path=path,
            message=f"Invalid value for operator {operator}: expected a semver string.",
        )
    semver_value = value
    if operator == "semver_wildcard":
        semver_value = semver_value.rstrip(".*")
    try:
        parse_semver(semver_value)
    except (ValueError, IndexError):
        return Violation(
            rule_id="cross_field.semver_value_invalid",
            path=path,
            message=f"Invalid semver value for operator {operator}: {value}.",
        )
    return None


def check_operator_value_compatibility(filters: Mapping[str, Any]) -> list[Violation]:
    violations = []
    for group_index, group in enumerate(filters.get("groups", [])):
        for prop_index, prop in enumerate(group.get("properties", [])):
            path = f"groups[{group_index}].properties[{prop_index}].value"
            operator = prop.get("operator")
            value = prop.get("value")
            if prop.get("type") == "flag" and operator != "flag_evaluates_to":
                violations.append(
                    Violation(
                        rule_id="cross_field.flag_property_requires_flag_evaluates_to",
                        path=f"groups[{group_index}].properties[{prop_index}].operator",
                        message="Flag properties must use the 'flag_evaluates_to' operator.",
                    )
                )
            if operator in ("in", "not_in") and prop.get("type") != "cohort":
                violations.append(
                    Violation(
                        rule_id="cross_field.in_not_in_requires_cohort",
                        path=f"groups[{group_index}].properties[{prop_index}].operator",
                        message=f"Operator {operator} is only supported on cohort properties.",
                    )
                )
            if operator in DATE_OPERATORS and determine_parsed_date_for_property_matching(value) is None:
                violations.append(
                    Violation(
                        rule_id="cross_field.date_value_not_parseable",
                        path=path,
                        message=f"Invalid date value: {value}.",
                    )
                )
            if operator in STRING_VALUE_OPERATORS and not isinstance(value, str):
                violations.append(
                    Violation(
                        rule_id="cross_field.operator_requires_string_value",
                        path=path,
                        message=f"Operator {operator} requires a string value.",
                    )
                )
            if operator in LIST_VALUE_OPERATORS and not isinstance(value, list):
                violations.append(
                    Violation(
                        rule_id="cross_field.operator_requires_list_value",
                        path=path,
                        message=f"Operator {operator} requires a list of values.",
                    )
                )
            if operator in SEMVER_OPERATORS:
                semver_violation = _check_semver_value(value, operator, path)
                if semver_violation is not None:
                    violations.append(semver_violation)
    return violations


CROSS_FIELD_CHECKS: tuple[Callable[[Mapping[str, Any]], list[Violation]], ...] = (
    check_variant_rollout_sum,
    check_variant_keys_unique,
    check_payload_keys,
    check_group_variant_references,
    check_property_types_match_aggregation,
    check_operator_value_compatibility,
)


def check_groups_non_empty_for_create(filters: Mapping[str, Any]) -> list[Violation]:
    # Deliberately NOT in CROSS_FIELD_CHECKS. The POST/PATCH asymmetry is a locked decision
    # on #50084: POST requires at least one condition group, but
    # PATCH {"filters": {"groups": []}} is a legitimate "clear targeting" under merged-state
    # validation, and stored flags with empty groups are valid state the audit must never
    # flag. Do not "unify" these in either direction.
    if not filters.get("groups"):
        return [
            Violation(
                rule_id="contextual.groups_empty_on_create",
                path="groups",
                message="Feature flags must have at least one condition set (group).",
            )
        ]
    return []


def collect_cross_field_violations(filters: Mapping[str, Any]) -> list[Violation]:
    return [violation for check in CROSS_FIELD_CHECKS for violation in check(filters)]


def validate_cross_field_or_raise(filters: Mapping[str, Any]) -> None:
    """Fail-fast wrapper over the same collectors, for the write path."""
    violations = collect_cross_field_violations(filters)
    if violations:
        raise serializers.ValidationError(
            [ErrorDetail(f"{violation.path}: {violation.message}", code=violation.rule_id) for violation in violations]
        )


_LIST_INDEX_RE = re.compile(r"\[\d+\]")


def flatten_structural_errors(errors: Any, path: str = "") -> list[Violation]:
    """Flatten DRF's nested error structure into Violations with stable rule ids.

    The rule id is the index-stripped path plus the ErrorDetail code (e.g.
    "structural.groups[].properties[].key.invalid"); concrete indices survive in the path.
    """
    violations: list[Violation] = []
    if isinstance(errors, dict):
        for key, child in errors.items():
            if isinstance(key, int):
                # ListField reports per-item errors as {index: errors}
                child_path = f"{path}[{key}]"
            elif key == api_settings.NON_FIELD_ERRORS_KEY:
                child_path = path
            else:
                child_path = f"{path}.{key}" if path else str(key)
            violations.extend(flatten_structural_errors(child, child_path))
    elif isinstance(errors, list):
        for index, item in enumerate(errors):
            if isinstance(item, (dict, list)):
                # many=True serializers report a list aligned by item index; empty dicts mark
                # valid items
                if item:
                    violations.extend(flatten_structural_errors(item, f"{path}[{index}]"))
            elif item:
                code = getattr(item, "code", None) or "invalid"
                rule_path = _LIST_INDEX_RE.sub("[]", path) or "filters"
                violations.append(
                    Violation(
                        rule_id=f"structural.{rule_path}.{code}",
                        path=path or "filters",
                        message=str(item),
                    )
                )
    return violations


def collect_filters_violations(filters: Any, *, context: dict[str, Any] | None = None) -> list[Violation]:
    """Run the full structural + cross-field rule set against one filters value.

    Cross-field checks only run once the structure is valid — the same ordering the write
    path has (field validation raises before object-level validation), and it lets the
    cross-field rules trust types instead of re-checking them.
    """
    if not isinstance(filters, dict):
        return [
            Violation(
                rule_id="structural.filters.not_a_dict",
                path="filters",
                message=f"Filters must be a dict, got {type(filters).__name__}.",
            )
        ]
    serializer = FeatureFlagFiltersSerializer(data=filters, context=context or {})
    if not serializer.is_valid():
        return flatten_structural_errors(serializer.errors)
    return collect_cross_field_violations(serializer.validated_data)
