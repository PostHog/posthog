from importlib import import_module
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.feature_flags.backend.filters_validation import collect_filters_violations

_migration = import_module("products.feature_flags.backend.migrations.0011_clean_flag_filters_recoverable_violations")
_clean_filters = _migration._clean_filters

# (name, dirty, expected, expected_rules, audit_clean_after)
# audit_clean_after is False for cases that deliberately leave unrecoverable
# violations in place (unknown operators, junk rollout strings, bool values).
CASES: list[tuple[str, dict[str, Any], dict[str, Any] | None, set[str], bool]] = [
    (
        "payload_raw_string_reencoded_valid_json_untouched",
        {
            "groups": [],
            "multivariate": {
                "variants": [{"key": "v1", "rollout_percentage": 50.0}, {"key": "v2", "rollout_percentage": 50.0}]
            },
            "payloads": {"v1": "hello world", "v2": '{"a": 1}'},
        },
        {
            "groups": [],
            "multivariate": {
                "variants": [{"key": "v1", "rollout_percentage": 50.0}, {"key": "v2", "rollout_percentage": 50.0}]
            },
            "payloads": {"v1": '"hello world"', "v2": '{"a": 1}'},
        },
        {"payload_not_json"},
        True,
    ),
    (
        "payload_nan_token_reencoded_as_string",
        {"groups": [], "payloads": {"true": "NaN"}},
        {"groups": [], "payloads": {"true": '"NaN"'}},
        {"payload_not_json"},
        True,
    ),
    (
        "in_not_in_remapped_on_person",
        {
            "groups": [
                {
                    "properties": [
                        {"key": "email", "type": "person", "operator": "in", "value": ["a", "b"]},
                        {"key": "plan", "type": "person", "operator": "not_in", "value": ["x"]},
                    ]
                }
            ]
        },
        {
            "groups": [
                {
                    "properties": [
                        {"key": "email", "type": "person", "operator": "exact", "value": ["a", "b"]},
                        {"key": "plan", "type": "person", "operator": "is_not", "value": ["x"]},
                    ]
                }
            ]
        },
        {"in_not_in_non_cohort"},
        True,
    ),
    (
        "cohort_in_operator_left_untouched",
        {"groups": [{"properties": [{"key": "id", "type": "cohort", "operator": "in", "value": 42}]}]},
        None,
        set(),
        True,
    ),
    (
        "operator_typos_mapped_unknown_left",
        {
            "groups": [
                {
                    "properties": [
                        {"key": "k", "type": "person", "operator": "contains", "value": "x"},
                        {"key": "k2", "type": "person", "operator": "matches regex", "value": "^a"},
                        {"key": "k3", "type": "person", "operator": "is_contained_within", "value": "y"},
                    ]
                }
            ]
        },
        {
            "groups": [
                {
                    "properties": [
                        {"key": "k", "type": "person", "operator": "icontains", "value": "x"},
                        {"key": "k2", "type": "person", "operator": "regex", "value": "^a"},
                        {"key": "k3", "type": "person", "operator": "is_contained_within", "value": "y"},
                    ]
                }
            ]
        },
        {"operator_typo"},
        False,
    ),
    (
        "numeric_string_rollout_coerced_junk_and_out_of_range_left",
        {"groups": [{"rollout_percentage": "50"}, {"rollout_percentage": "abc"}, {"rollout_percentage": "150"}]},
        {"groups": [{"rollout_percentage": 50.0}, {"rollout_percentage": "abc"}, {"rollout_percentage": "150"}]},
        {"rollout_percentage_string"},
        False,
    ),
    (
        "dangling_variant_override_nulled_valid_kept",
        {
            "groups": [{"variant": "ghost"}, {"variant": "real"}],
            "multivariate": {"variants": [{"key": "real", "rollout_percentage": 100}]},
        },
        {
            "groups": [{"variant": None}, {"variant": "real"}],
            "multivariate": {"variants": [{"key": "real", "rollout_percentage": 100}]},
        },
        {"dangling_variant_override"},
        True,
    ),
    (
        "numeric_value_stringified_bool_left",
        {
            "groups": [
                {
                    "properties": [
                        {"key": "v", "type": "person", "operator": "gt", "value": 5},
                        {"key": "b", "type": "person", "operator": "gt", "value": True},
                    ]
                }
            ]
        },
        {
            "groups": [
                {
                    "properties": [
                        {"key": "v", "type": "person", "operator": "gt", "value": "5"},
                        {"key": "b", "type": "person", "operator": "gt", "value": True},
                    ]
                }
            ]
        },
        {"non_string_value"},
        False,
    ),
    (
        "empty_multivariate_nulled_with_override_and_payload_keys",
        {
            "groups": [{"variant": "control"}],
            "multivariate": {"variants": []},
            "payloads": {"true": "1", "control": "2"},
        },
        {"groups": [{"variant": None}], "multivariate": None, "payloads": {"true": "1"}},
        {"multivariate_empty", "dangling_variant_override"},
        True,
    ),
    (
        "typo_remap_chains_into_stringification",
        {"groups": [{"properties": [{"key": "n", "type": "person", "operator": "contains", "value": 7}]}]},
        {"groups": [{"properties": [{"key": "n", "type": "person", "operator": "icontains", "value": "7"}]}]},
        {"operator_typo", "non_string_value"},
        True,
    ),
    (
        "fully_valid_flag_untouched",
        {
            "groups": [
                {
                    "properties": [{"key": "email", "type": "person", "operator": "icontains", "value": "@x.com"}],
                    "rollout_percentage": 50,
                    "variant": "a",
                }
            ],
            "multivariate": {"variants": [{"key": "a", "rollout_percentage": 100.0}]},
            "payloads": {"a": '"payload"'},
            "aggregation_group_type_index": None,
        },
        None,
        set(),
        True,
    ),
]


class TestCleanFiltersTransform(SimpleTestCase):
    @parameterized.expand([(name, dirty, expected, rules) for name, dirty, expected, rules, _ in CASES])
    def test_transform(self, _name: str, dirty: dict, expected: dict | None, expected_rules: set[str]) -> None:
        cleaned, rules = _clean_filters(dirty)
        assert rules == expected_rules
        assert cleaned == (dirty if expected is None else expected)

    @parameterized.expand([(name, dirty) for name, dirty, *_ in CASES])
    def test_transform_is_idempotent(self, _name: str, dirty: dict) -> None:
        cleaned, _ = _clean_filters(dirty)
        second, second_rules = _clean_filters(cleaned)
        assert second == cleaned
        assert second_rules == set()

    @parameterized.expand([(name, dirty) for name, dirty, _, _, audit_clean in CASES if audit_clean])
    def test_recoverable_output_passes_the_audit_rule_set(self, _name: str, dirty: dict) -> None:
        cleaned, _ = _clean_filters(dirty)
        assert collect_filters_violations(cleaned) == []
