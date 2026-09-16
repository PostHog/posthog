import re
import json
import hashlib
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from jsonschema import Draft202012Validator, FormatChecker
from parameterized import parameterized

from products.feature_flags.backend.api.feature_flag import calculate_filter_size_bytes
from products.feature_flags.backend.facade.config_validation import (
    _UUID as UUID_PATTERN,
    ASSIGNMENT_ALGORITHM,
    MAX_PREDICATES_PER_RULE,
    MAX_RULES,
    MAX_SEED_LENGTH,
    PERSON_ASSIGNMENT,
    PROPERTY_OPERATORS,
    PROPERTY_TYPES,
    ROLLOUT_MISS_POLICIES,
    ConfigValidationError,
    Predicate,
    ValidatedConfig,
    ValidatedRule,
    ValidationLimits,
    _encoded_size as config_size_bytes,
    validate_config,
)

# Vendored from the released harness contract; SOURCE.json records the revision and digests.
CONTRACT_DIR = Path(__file__).parent / "fixtures" / "rules_v2_contract" / "2.0.0"
LIMITS = ValidationLimits(max_config_bytes=64 * 1024, max_metadata_bytes=1024)

TARGETED_ID = "11111111-1111-4111-8111-111111111111"
ROLLOUT_ID = "22222222-2222-4222-8222-222222222222"
SEED = "release-preview"


def targeted(**overrides: Any) -> dict[str, Any]:
    return {
        "id": TARGETED_ID,
        "rule_type": "targeted_release",
        "targeting": {"properties": []},
        "value": True,
        **overrides,
    }


def rollout(**overrides: Any) -> dict[str, Any]:
    return {
        "id": ROLLOUT_ID,
        "rule_type": "percentage_rollout",
        "targeting": {"properties": []},
        "value": True,
        "rollout_percentage": 25,
        "on_rollout_miss": "continue",
        "assignment_algorithm": ASSIGNMENT_ALGORITHM,
        "seed": SEED,
        **overrides,
    }


def person(**overrides: Any) -> dict[str, Any]:
    return {"key": "account_tier", "type": "person", "operator": "exact", "value": "preview", **overrides}


def config(*rules: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    return {"version": 2, "return_type": "boolean", "default_value": False, "rules": list(rules), **overrides}


def without(document: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: value for name, value in document.items() if name != key}


def errors_of(document: object, limits: ValidationLimits = LIMITS) -> list[tuple[str, str]]:
    with pytest.raises(ConfigValidationError) as exc_info:
        validate_config(document, limits=limits)
    return [(error.code, error.attr) for error in exc_info.value.errors]


def load_contract(relative: str) -> Any:
    with (CONTRACT_DIR / relative).open(encoding="utf-8") as handle:
        return json.load(handle)


MANIFEST = load_contract("manifest.json")
CONFIG_SCHEMA = load_contract("schemas/config.schema.json")
SCHEMA_VALIDATOR = Draft202012Validator(CONFIG_SCHEMA, format_checker=FormatChecker())
CONTRACT_FIXTURES = [entry for entry in MANIFEST["artifacts"] if entry["kind"] == "fixture"]


VALID_DOCUMENTS: list[tuple[str, dict[str, Any]]] = [
    ("empty_rules", config()),
    ("null_default", config(default_value=None)),
    ("float_version_literal", config(version=2.0)),
    ("targeted_with_person_property", config(targeted(targeting={"properties": [person()]}))),
    ("targeted_without_operator", config(targeted(targeting={"properties": [person(operator=None, negation=None)]}))),
    ("targeted_false_value", config(targeted(value=False))),
    ("description_and_metadata", config(targeted(description="Preview accounts", metadata={"color": "blue"}))),
    ("empty_metadata", config(targeted(metadata={}))),
    ("percentage_two_decimals", config(rollout(rollout_percentage=33.33))),
    ("percentage_zero", config(rollout(rollout_percentage=0))),
    ("percentage_hundred", config(rollout(rollout_percentage=100))),
    ("percentage_float_integer", config(rollout(rollout_percentage=25.0))),
    ("return_default", config(rollout(on_rollout_miss="return_default"))),
    ("explicit_person_assignment", config(rollout(assign_by=PERSON_ASSIGNMENT))),
    ("seed_max_length", config(rollout(seed="s" * 400))),
    (
        "all_operator_value_shapes",
        config(
            targeted(
                targeting={
                    "properties": [
                        person(key="email", operator="icontains", value="@example.com"),
                        person(key="version", operator="semver_gte", value="1.2.3"),
                        person(key="version", operator="semver_wildcard", value="1.*"),
                        person(key="signup", operator="is_date_after", value="2024-01-01"),
                        person(key="seats", operator="gt", value=10),
                        person(key="seats", operator="lt", value="10"),
                        person(key="tags", operator="icontains_multi", value=["a", "b"]),
                        person(key="beta", operator="is_set"),
                        person(key="beta", operator="is_not_set", value=None),
                        person(key="plan", operator="exact", value=["pro", "team"], negation=True),
                        person(
                            key="plan",
                            operator="is_not",
                            value="free",
                            label="Plan",
                            cohort_name=None,
                            group_key_names=None,
                        ),
                    ]
                }
            )
        ),
    ),
    ("max_rules", config(*[targeted(id=f"00000000-0000-4000-8000-{index:012d}") for index in range(MAX_RULES)])),
    (
        "max_predicates",
        config(targeted(targeting={"properties": [person(key=f"k{i}") for i in range(MAX_PREDICATES_PER_RULE)]})),
    ),
]

INVALID_DOCUMENTS: list[tuple[str, object, list[tuple[str, str]]]] = [
    ("root_list", [], [("invalid", "filters")]),
    ("root_none", None, [("invalid", "filters")]),
    ("root_string", "{}", [("invalid", "filters")]),
    ("root_not_json", {**config(), "note": {1, 2}}, [("invalid", "filters")]),
    ("missing_version", without(config(), "version"), [("required", "filters.version")]),
    ("version_1", config(version=1), [("invalid", "filters.version")]),
    ("version_string", config(version="2"), [("invalid", "filters.version")]),
    ("version_bool", config(version=True), [("invalid", "filters.version")]),
    ("version_null", config(version=None), [("invalid", "filters.version")]),
    ("version_3", config(version=3), [("invalid", "filters.version")]),
    ("version_fraction", config(version=2.5), [("invalid", "filters.version")]),
    ("unknown_root_field", config(future=1), [("unknown_field", "filters.future")]),
    ("v1_groups", config(groups=[]), [("unknown_field", "filters.groups")]),
    (
        "v1_multivariate_and_payloads",
        config(multivariate=None, payloads={}),
        [("unknown_field", "filters.multivariate"), ("unknown_field", "filters.payloads")],
    ),
    ("missing_return_type", without(config(), "return_type"), [("required", "filters.return_type")]),
    ("return_type_unknown", config(return_type="json"), [("invalid", "filters.return_type")]),
    ("return_type_null", config(return_type=None), [("invalid", "filters.return_type")]),
    ("return_type_string", config(return_type="string", default_value="a"), [("unsupported", "filters.return_type")]),
    ("return_type_number", config(return_type="number", default_value=0), [("unsupported", "filters.return_type")]),
    ("return_type_object", config(return_type="object", default_value={}), [("unsupported", "filters.return_type")]),
    ("missing_default", without(config(), "default_value"), [("required", "filters.default_value")]),
    ("default_zero", config(default_value=0), [("invalid", "filters.default_value")]),
    ("default_one", config(default_value=1), [("invalid", "filters.default_value")]),
    ("default_string", config(default_value="true"), [("invalid", "filters.default_value")]),
    ("default_list", config(default_value=[]), [("invalid", "filters.default_value")]),
    (
        "group_assignment",
        config(aggregation_group_type_index=0),
        [("unsupported", "filters.aggregation_group_type_index")],
    ),
    (
        "group_index_string",
        config(aggregation_group_type_index="0"),
        [("invalid", "filters.aggregation_group_type_index")],
    ),
    (
        "group_index_null",
        config(aggregation_group_type_index=None),
        [("invalid", "filters.aggregation_group_type_index")],
    ),
    (
        "group_index_bool",
        config(aggregation_group_type_index=True),
        [("invalid", "filters.aggregation_group_type_index")],
    ),
    (
        "group_index_float",
        config(aggregation_group_type_index=1.0),
        [("invalid", "filters.aggregation_group_type_index")],
    ),
    ("missing_rules", without(config(), "rules"), [("required", "filters.rules")]),
    ("rules_object", config(rules={}), [("invalid", "filters.rules")]),
    ("rules_null", config(rules=None), [("invalid", "filters.rules")]),
    (
        "too_many_rules",
        config(*[targeted(id=f"00000000-0000-4000-8000-{i:012d}") for i in range(MAX_RULES + 1)]),
        [("limit_exceeded", "filters.rules")],
    ),
    ("rule_number", config(rules=[1]), [("invalid", "filters.rules[0]")]),
    ("rule_null", config(rules=[None]), [("invalid", "filters.rules[0]")]),
    ("missing_rule_type", config(without(targeted(), "rule_type")), [("required", "filters.rules[0].rule_type")]),
    ("removed_rule_type", config(targeted(rule_type="variant_rollout")), [("invalid", "filters.rules[0].rule_type")]),
    ("rule_type_null", config(targeted(rule_type=None)), [("invalid", "filters.rules[0].rule_type")]),
    ("rule_type_list", config(targeted(rule_type=["targeted_release"])), [("invalid", "filters.rules[0].rule_type")]),
    ("experiment_rule", config(targeted(rule_type="experiment")), [("unsupported", "filters.rules[0].rule_type")]),
    (
        "unknown_rule_field",
        config(targeted(implicit_default=False)),
        [("unknown_field", "filters.rules[0].implicit_default")],
    ),
    (
        "targeted_with_rollout_fields",
        config(targeted(rollout_percentage=25, seed=SEED)),
        [("unknown_field", "filters.rules[0].rollout_percentage"), ("unknown_field", "filters.rules[0].seed")],
    ),
    (
        "targeted_with_experiment_fields",
        config(targeted(experiment_id=1, variants=[], holdout=None)),
        [
            ("unknown_field", "filters.rules[0].experiment_id"),
            ("unknown_field", "filters.rules[0].variants"),
            ("unknown_field", "filters.rules[0].holdout"),
        ],
    ),
    ("missing_id", config(without(targeted(), "id")), [("required", "filters.rules[0].id")]),
    ("id_not_uuid", config(targeted(id="rule-1")), [("invalid", "filters.rules[0].id")]),
    (
        "id_without_hyphens",
        config(targeted(id="11111111111141118111111111111111")),
        [("invalid", "filters.rules[0].id")],
    ),
    ("id_braced", config(targeted(id="{11111111-1111-4111-8111-111111111111}")), [("invalid", "filters.rules[0].id")]),
    ("id_number", config(targeted(id=1)), [("invalid", "filters.rules[0].id")]),
    ("duplicate_ids", config(targeted(), rollout(id=TARGETED_ID)), [("not_unique", "filters.rules[1].id")]),
    ("missing_targeting", config(without(targeted(), "targeting")), [("required", "filters.rules[0].targeting")]),
    ("targeting_list", config(targeted(targeting=[])), [("invalid", "filters.rules[0].targeting")]),
    (
        "targeting_without_properties",
        config(targeted(targeting={})),
        [("required", "filters.rules[0].targeting.properties")],
    ),
    (
        "targeting_unknown_field",
        config(targeted(targeting={"properties": [], "rollout_percentage": 50})),
        [("unknown_field", "filters.rules[0].targeting.rollout_percentage")],
    ),
    (
        "properties_object",
        config(targeted(targeting={"properties": {}})),
        [("invalid", "filters.rules[0].targeting.properties")],
    ),
    (
        "too_many_properties",
        config(targeted(targeting={"properties": [person(key=f"k{i}") for i in range(MAX_PREDICATES_PER_RULE + 1)]})),
        [("limit_exceeded", "filters.rules[0].targeting.properties")],
    ),
    (
        "property_number",
        config(targeted(targeting={"properties": [1]})),
        [("invalid", "filters.rules[0].targeting.properties[0]")],
    ),
    (
        "property_unknown_field",
        config(targeted(targeting={"properties": [person(future=1)]})),
        [("unknown_field", "filters.rules[0].targeting.properties[0].future")],
    ),
    (
        "property_missing_key",
        config(targeted(targeting={"properties": [without(person(), "key")]})),
        [("required", "filters.rules[0].targeting.properties[0].key")],
    ),
    (
        "property_empty_key",
        config(targeted(targeting={"properties": [person(key="")]})),
        [("invalid", "filters.rules[0].targeting.properties[0].key")],
    ),
    (
        "property_numeric_key",
        config(targeted(targeting={"properties": [person(key=1)]})),
        [("invalid", "filters.rules[0].targeting.properties[0].key")],
    ),
    (
        "property_missing_type",
        config(targeted(targeting={"properties": [without(person(), "type")]})),
        [("required", "filters.rules[0].targeting.properties[0].type")],
    ),
    (
        "property_unknown_type",
        config(targeted(targeting={"properties": [person(type="event")]})),
        [("invalid", "filters.rules[0].targeting.properties[0].type")],
    ),
    (
        "cohort_property",
        config(targeted(targeting={"properties": [{"key": "id", "type": "cohort", "value": 7, "operator": "in"}]})),
        [("unsupported", "filters.rules[0].targeting.properties[0].type")],
    ),
    (
        "flag_property",
        config(
            targeted(
                targeting={
                    "properties": [{"key": "12", "type": "flag", "value": True, "operator": "flag_evaluates_to"}]
                }
            )
        ),
        [("unsupported", "filters.rules[0].targeting.properties[0].type")],
    ),
    (
        "group_property",
        config(targeted(targeting={"properties": [person(type="group", group_type_index=0)]})),
        [("unsupported", "filters.rules[0].targeting.properties[0].type")],
    ),
    (
        "operator_alias",
        config(targeted(targeting={"properties": [person(operator="min", value=1)]})),
        [("invalid", "filters.rules[0].targeting.properties[0].operator")],
    ),
    (
        "operator_unknown",
        config(targeted(targeting={"properties": [person(operator="contains")]})),
        [("invalid", "filters.rules[0].targeting.properties[0].operator")],
    ),
    (
        "operator_list",
        config(targeted(targeting={"properties": [person(operator=["exact"])]})),
        [("invalid", "filters.rules[0].targeting.properties[0].operator")],
    ),
    (
        "operator_cohort_only",
        config(targeted(targeting={"properties": [person(operator="in", value=[1])]})),
        [("invalid", "filters.rules[0].targeting.properties[0].operator")],
    ),
    (
        "operator_flag_only",
        config(targeted(targeting={"properties": [person(operator="flag_evaluates_to", value=True)]})),
        [("invalid", "filters.rules[0].targeting.properties[0].operator")],
    ),
    (
        "date_value",
        config(targeted(targeting={"properties": [person(operator="is_date_before", value="not a date")]})),
        [("invalid", "filters.rules[0].targeting.properties[0].value")],
    ),
    (
        "string_operator_number",
        config(targeted(targeting={"properties": [person(operator="icontains", value=1)]})),
        [("invalid", "filters.rules[0].targeting.properties[0].value")],
    ),
    (
        "regex_null",
        config(targeted(targeting={"properties": [person(operator="regex", value=None)]})),
        [("invalid", "filters.rules[0].targeting.properties[0].value")],
    ),
    (
        "prefix_operator_list",
        config(targeted(targeting={"properties": [person(operator="starts_with", value=["a"])]})),
        [("invalid", "filters.rules[0].targeting.properties[0].value")],
    ),
    (
        "numeric_operator_list",
        config(targeted(targeting={"properties": [person(operator="gte", value=[])]})),
        [("invalid", "filters.rules[0].targeting.properties[0].value")],
    ),
    (
        "numeric_operator_bool",
        config(targeted(targeting={"properties": [person(operator="gt", value=True)]})),
        [("invalid", "filters.rules[0].targeting.properties[0].value")],
    ),
    (
        "list_operator_string",
        config(targeted(targeting={"properties": [person(operator="icontains_multi", value="a")]})),
        [("invalid", "filters.rules[0].targeting.properties[0].value")],
    ),
    (
        "semver_not_a_version",
        config(targeted(targeting={"properties": [person(operator="semver_gt", value="not-a-version")]})),
        [("invalid", "filters.rules[0].targeting.properties[0].value")],
    ),
    (
        "semver_number",
        config(targeted(targeting={"properties": [person(operator="semver_eq", value=1)]})),
        [("invalid", "filters.rules[0].targeting.properties[0].value")],
    ),
    (
        "exact_nan",
        config(targeted(targeting={"properties": [person(value=float("nan"))]})),
        [("invalid", "filters.rules[0].targeting.properties[0].value")],
    ),
    (
        "omitted_operator_nan",
        config(targeted(targeting={"properties": [without(person(), "operator") | {"value": float("nan")}]})),
        [("invalid", "filters.rules[0].targeting.properties[0].value")],
    ),
    (
        "null_operator_infinity",
        config(targeted(targeting={"properties": [person(operator=None, value=float("inf"))]})),
        [("invalid", "filters.rules[0].targeting.properties[0].value")],
    ),
    (
        "exact_nested_infinity",
        config(targeted(targeting={"properties": [person(value=[1, {"n": float("inf")}])]})),
        [("invalid", "filters.rules[0].targeting.properties[0].value")],
    ),
    (
        "person_with_group_type_index",
        config(targeted(targeting={"properties": [person(group_type_index=0)]})),
        [("invalid", "filters.rules[0].targeting.properties[0].group_type_index")],
    ),
    (
        "negation_string",
        config(targeted(targeting={"properties": [person(negation="yes")]})),
        [("invalid", "filters.rules[0].targeting.properties[0].negation")],
    ),
    (
        "label_number",
        config(targeted(targeting={"properties": [person(label=1)]})),
        [("invalid", "filters.rules[0].targeting.properties[0].label")],
    ),
    (
        "cohort_name_number",
        config(targeted(targeting={"properties": [person(cohort_name=1)]})),
        [("invalid", "filters.rules[0].targeting.properties[0].cohort_name")],
    ),
    (
        "group_key_names_string",
        config(targeted(targeting={"properties": [person(group_key_names="org")]})),
        [("invalid", "filters.rules[0].targeting.properties[0].group_key_names")],
    ),
    (
        "group_key_names_non_string_value",
        config(targeted(targeting={"properties": [person(group_key_names={"org": 1})]})),
        [("invalid", "filters.rules[0].targeting.properties[0].group_key_names")],
    ),
    ("description_null", config(targeted(description=None)), [("invalid", "filters.rules[0].description")]),
    ("description_number", config(targeted(description=1)), [("invalid", "filters.rules[0].description")]),
    ("metadata_list", config(targeted(metadata=[])), [("invalid", "filters.rules[0].metadata")]),
    ("metadata_string", config(targeted(metadata="x")), [("invalid", "filters.rules[0].metadata")]),
    ("metadata_nan", config(targeted(metadata={"n": float("nan")})), [("invalid", "filters.rules[0].metadata")]),
    (
        "metadata_too_large",
        config(targeted(metadata={"blob": "x" * 2000})),
        [("limit_exceeded", "filters.rules[0].metadata")],
    ),
    ("missing_value", config(without(targeted(), "value")), [("required", "filters.rules[0].value")]),
    ("value_null", config(targeted(value=None)), [("invalid", "filters.rules[0].value")]),
    ("value_zero", config(rollout(value=0)), [("invalid", "filters.rules[0].value")]),
    ("value_one", config(targeted(value=1)), [("invalid", "filters.rules[0].value")]),
    ("value_string", config(targeted(value="true")), [("invalid", "filters.rules[0].value")]),
    (
        "missing_rollout_percentage",
        config(without(rollout(), "rollout_percentage")),
        [("required", "filters.rules[0].rollout_percentage")],
    ),
    ("rollout_bool", config(rollout(rollout_percentage=True)), [("invalid", "filters.rules[0].rollout_percentage")]),
    ("rollout_string", config(rollout(rollout_percentage="25")), [("invalid", "filters.rules[0].rollout_percentage")]),
    ("rollout_null", config(rollout(rollout_percentage=None)), [("invalid", "filters.rules[0].rollout_percentage")]),
    (
        "rollout_nan",
        config(rollout(rollout_percentage=float("nan"))),
        [("invalid", "filters.rules[0].rollout_percentage")],
    ),
    (
        "rollout_infinity",
        config(rollout(rollout_percentage=float("inf"))),
        [("invalid", "filters.rules[0].rollout_percentage")],
    ),
    ("rollout_negative", config(rollout(rollout_percentage=-1)), [("invalid", "filters.rules[0].rollout_percentage")]),
    (
        "rollout_above_maximum",
        config(rollout(rollout_percentage=100.01)),
        [("invalid", "filters.rules[0].rollout_percentage")],
    ),
    (
        "rollout_three_decimals",
        config(rollout(rollout_percentage=33.333)),
        [("invalid", "filters.rules[0].rollout_percentage")],
    ),
    (
        "rollout_tiny_fraction",
        config(rollout(rollout_percentage=1e-7)),
        [("invalid", "filters.rules[0].rollout_percentage")],
    ),
    (
        "missing_miss_policy",
        config(without(rollout(), "on_rollout_miss")),
        [("required", "filters.rules[0].on_rollout_miss")],
    ),
    ("unknown_miss_policy", config(rollout(on_rollout_miss="stop")), [("invalid", "filters.rules[0].on_rollout_miss")]),
    ("null_miss_policy", config(rollout(on_rollout_miss=None)), [("invalid", "filters.rules[0].on_rollout_miss")]),
    (
        "missing_algorithm",
        config(without(rollout(), "assignment_algorithm")),
        [("required", "filters.rules[0].assignment_algorithm")],
    ),
    (
        "unknown_algorithm",
        config(rollout(assignment_algorithm="md5")),
        [("invalid", "filters.rules[0].assignment_algorithm")],
    ),
    ("missing_seed", config(without(rollout(), "seed")), [("required", "filters.rules[0].seed")]),
    ("empty_seed", config(rollout(seed="")), [("invalid", "filters.rules[0].seed")]),
    ("seed_too_long", config(rollout(seed="s" * 401)), [("invalid", "filters.rules[0].seed")]),
    ("seed_number", config(rollout(seed=123)), [("invalid", "filters.rules[0].seed")]),
    ("seed_null", config(rollout(seed=None)), [("invalid", "filters.rules[0].seed")]),
    ("group_assign_by", config(rollout(assign_by="group")), [("invalid", "filters.rules[0].assign_by")]),
    ("null_assign_by", config(rollout(assign_by=None)), [("invalid", "filters.rules[0].assign_by")]),
]


class TestValidateConfig:
    @parameterized.expand(VALID_DOCUMENTS)
    def test_admitted_documents_validate_and_match_the_canonical_schema(
        self, _name: str, document: dict[str, Any]
    ) -> None:
        snapshot = deepcopy(document)
        validated = validate_config(document, limits=LIMITS)
        assert [rule.id for rule in validated.rules] == [rule["id"] for rule in document["rules"]]
        assert document == snapshot
        # Admission is narrower than the contract, never wider: everything accepted here is schema-valid.
        assert not list(SCHEMA_VALIDATOR.iter_errors(document))

    @parameterized.expand(INVALID_DOCUMENTS)
    def test_rejected_documents_report_deterministic_field_errors(
        self, _name: str, document: object, expected: list[tuple[str, str]]
    ) -> None:
        snapshot = deepcopy(document) if isinstance(document, dict | list) else document
        assert errors_of(document) == expected
        assert errors_of(document) == expected
        if isinstance(document, dict | list):
            assert document == snapshot

    def test_errors_are_collected_in_a_fixed_order(self) -> None:
        document = {**without(config(targeted(id="bad")), "default_value"), "future": 1}
        with pytest.raises(ConfigValidationError) as exc_info:
            validate_config(document, limits=LIMITS)
        assert [(error.code, error.attr) for error in exc_info.value.errors] == [
            ("unknown_field", "filters.future"),
            ("required", "filters.default_value"),
            ("invalid", "filters.rules[0].id"),
        ]
        assert str(exc_info.value) == "filters.future: Unknown field."

    def test_unsupported_family_is_reported_before_shape_of_its_values(self) -> None:
        # A canonical string document is refused for the family, not for values this validator cannot judge.
        document = config(targeted(value="compact"), return_type="string", default_value="standard")
        assert errors_of(document) == [("unsupported", "filters.return_type")]

    def test_v1_only_fields_name_the_format_clash(self) -> None:
        with pytest.raises(ConfigValidationError) as exc_info:
            validate_config(config(groups=[], future=1), limits=LIMITS)
        details = {error.attr: error.detail for error in exc_info.value.errors}
        assert "version 1" in details["filters.groups"]
        assert details["filters.future"] == "Unknown field."

    def test_configuration_byte_limit_is_checked_first(self) -> None:
        limits = ValidationLimits(max_config_bytes=80, max_metadata_bytes=1024)
        assert errors_of(config(targeted(rule_type="nonsense")), limits) == [("limit_exceeded", "filters")]
        assert validate_config(config(), limits=limits).rules == ()

    @parameterized.expand([("zero", 0), ("negative", -1), ("bool", True), ("string", "1"), ("float", 1.5)])
    def test_limits_must_be_positive_integers(self, _name: str, limit: object) -> None:
        with pytest.raises(ValueError):
            ValidationLimits(max_config_bytes=limit, max_metadata_bytes=1)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            ValidationLimits(max_config_bytes=1, max_metadata_bytes=limit)  # type: ignore[arg-type]

    def test_validated_representation_carries_the_evaluated_fields(self) -> None:
        document = config(
            targeted(
                targeting={
                    "properties": [
                        person(operator=None, negation=None),
                        person(key="beta", operator="is_set", value=None),
                    ]
                }
            ),
            rollout(rollout_percentage=33.33, assign_by=PERSON_ASSIGNMENT, metadata={"note": "x"}),
            default_value=None,
        )
        validated = validate_config(document, limits=LIMITS)
        assert validated == ValidatedConfig(
            default_value=None,
            rules=(
                ValidatedRule(
                    id=TARGETED_ID,
                    rule_type="targeted_release",
                    predicates=frozenset(
                        {
                            Predicate(key="account_tier", operator="exact", value='"preview"', negation=False),
                            Predicate(key="beta", operator="is_set", value="null", negation=False),
                        }
                    ),
                    value=True,
                ),
                ValidatedRule(
                    id=ROLLOUT_ID,
                    rule_type="percentage_rollout",
                    predicates=frozenset(),
                    value=True,
                    rollout_percentage=Decimal("33.33"),
                    on_rollout_miss="continue",
                    seed=SEED,
                ),
            ),
        )
        assert validated.rules[1].rollout_percentage == Decimal("33.33")
        assert SEED not in repr(validated)

    @parameterized.expand([("explicit", {"negation": True}), ("omitted", {})])
    def test_predicates_are_canonical_across_equivalent_spellings(self, _name: str, extra: dict[str, Any]) -> None:
        plain = validate_config(config(targeted(targeting={"properties": [person(**extra)]})), limits=LIMITS)
        spelled = validate_config(
            config(targeted(targeting={"properties": [person(negation=extra.get("negation", None), label="Tier")]})),
            limits=LIMITS,
        )
        assert plain.rules[0].predicates == spelled.rules[0].predicates


def _contract_path(instance_path: str, expected: dict[str, Any]) -> str:
    attr = "filters" + re.sub(r"/(\d+)", r"[\1]", instance_path).replace("/", ".")
    if expected["keyword"] in ("required", "additionalProperties"):
        attr += "." + expected["message_contains"]
    return attr


def _admitted_family(document: dict[str, Any]) -> bool:
    raw_rules = document.get("rules")
    rules: list[dict[str, Any]] = (
        [rule for rule in raw_rules if isinstance(rule, dict)] if isinstance(raw_rules, list) else []
    )
    properties: list[dict[str, Any]] = [
        prop
        for rule in rules
        if isinstance(rule.get("targeting"), dict)
        for prop in rule["targeting"].get("properties", [])
        if isinstance(prop, dict)
    ]
    return (
        document.get("return_type") == "boolean"
        and "aggregation_group_type_index" not in document
        and all(rule.get("rule_type") != "experiment" for rule in rules)
        and all(prop.get("type") == "person" for prop in properties)
    )


class TestReleasedContract:
    def test_vendored_contract_is_intact(self) -> None:
        source = load_contract("SOURCE.json")
        index_bytes = (CONTRACT_DIR / "SHA256SUMS").read_bytes()
        assert hashlib.sha256(index_bytes).hexdigest() == source["source_sha256sums_digest"]
        index = {
            path: digest for digest, path in re.findall(r"^([0-9a-f]{64})  (.+)$", index_bytes.decode("utf-8"), re.M)
        }
        vendored = [
            path
            for path in CONTRACT_DIR.rglob("*")
            if path.is_file() and path.name not in ("SHA256SUMS", "SOURCE.json")
        ]
        relatives = {path.relative_to(CONTRACT_DIR).as_posix() for path in vendored}
        # A deliberate subset of the upstream index: the corpus and wire files stay with the Rust runner.
        assert relatives <= set(index)
        for path in vendored:
            relative = path.relative_to(CONTRACT_DIR).as_posix()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == index[relative], relative
        assert {entry["path"] for entry in CONTRACT_FIXTURES} <= relatives
        assert MANIFEST["contract"]["version"] == source["contract_version"]
        versions = {artifact["path"]: artifact.get("version") for artifact in MANIFEST["artifacts"]}
        assert versions["schemas/config.schema.json"] == source["config_schema_version"]
        assert versions["registries/literals.json"] == source["registry_version"]

    def test_literals_agree_with_the_released_registry(self) -> None:
        registry = load_contract("registries/literals.json")
        assert PROPERTY_OPERATORS == set(registry["property_operators"])
        assert set(PROPERTY_TYPES) == set(registry["property_types"])
        assert set(ROLLOUT_MISS_POLICIES) == set(registry["rollout_miss_policies"])
        assert [ASSIGNMENT_ALGORITHM] == registry["assignment_algorithms"]
        assert [PERSON_ASSIGNMENT] == registry["assignment_targets"]
        assert MAX_RULES == CONFIG_SCHEMA["properties"]["rules"]["maxItems"]
        assert MAX_PREDICATES_PER_RULE == CONFIG_SCHEMA["$defs"]["targeting"]["properties"]["properties"]["maxItems"]
        assert MAX_SEED_LENGTH == CONFIG_SCHEMA["$defs"]["seed"]["maxLength"]
        assert UUID_PATTERN.pattern == CONFIG_SCHEMA["$defs"]["uuid"]["pattern"]

    def test_size_check_measures_the_same_bytes_as_the_v1_limit(self) -> None:
        document = config(targeted(targeting={"properties": [person(value="ø")]}, metadata={"note": "x"}))
        assert config_size_bytes(document) == calculate_filter_size_bytes(document)

    @parameterized.expand([(entry["fixture_id"], entry) for entry in CONTRACT_FIXTURES if entry["expected"] == "valid"])
    def test_canonical_fixtures_are_never_relabelled_as_malformed(self, _name: str, entry: dict[str, Any]) -> None:
        document = load_contract(entry["path"])
        if _admitted_family(document):
            validate_config(document, limits=LIMITS)
            return
        # Schema-valid documents outside the admitted family are refused for that reason alone.
        assert {code for code, _ in errors_of(document)} == {"unsupported"}

    @parameterized.expand(
        [(entry["fixture_id"], entry) for entry in CONTRACT_FIXTURES if entry["expected"] == "invalid"]
    )
    def test_schema_invalid_fixtures_are_rejected(self, _name: str, entry: dict[str, Any]) -> None:
        document = load_contract(entry["path"])
        errors = errors_of(document)
        if _admitted_family(document):
            expected_attr = _contract_path(entry["expected_failure"]["instance_path"], entry["expected_failure"])
            assert any(code != "unsupported" and attr == expected_attr for code, attr in errors), (
                errors,
                expected_attr,
            )
        else:
            assert errors
