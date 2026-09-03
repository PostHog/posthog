from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail

from products.feature_flags.backend.api.feature_flag import _reject_serde_unsafe_filters
from products.feature_flags.backend.api.filters_schema import FeatureFlagFiltersSerializer
from products.feature_flags.backend.encrypted_flag_payloads import REDACTED_PAYLOAD_VALUE
from products.feature_flags.backend.filters_validation import (
    CROSS_FIELD_CHECKS,
    Violation,
    check_groups_non_empty_for_create,
    check_variant_rollout_sum,
    collect_cross_field_violations,
    collect_filters_violations,
    flatten_structural_errors,
)


def _multivariate(*variants: tuple[str, float]) -> dict[str, Any]:
    return {"variants": [{"key": key, "rollout_percentage": rollout} for key, rollout in variants]}


def _person_prop(**overrides: Any) -> dict[str, Any]:
    return {"key": "email", "type": "person", "operator": "icontains", "value": "@posthog.com", **overrides}


class TestFiltersValidation(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "variant_sum_under_100",
                {"multivariate": _multivariate(("a", 50), ("b", 49.9))},
                ["cross_field.variant_rollout_sum_not_100"],
            ),
            ("variant_sum_exactly_100", {"multivariate": _multivariate(("a", 50), ("b", 50))}, []),
            # Sums to 100.00000000000001; the flag UI accepts the same split.
            (
                "variant_sum_100_with_float_drift",
                {"multivariate": _multivariate(("a", 0.01), ("b", 64.04), ("c", 35.95))},
                [],
            ),
            # The smallest miss the flag UI can express, so the tolerance cannot swallow it.
            (
                "variant_sum_short_by_smallest_step",
                {"multivariate": _multivariate(("a", 50), ("b", 49.99))},
                ["cross_field.variant_rollout_sum_not_100"],
            ),
            (
                "variant_keys_duplicated",
                {"multivariate": _multivariate(("a", 50), ("a", 50))},
                ["cross_field.variant_keys_not_unique"],
            ),
            (
                "payload_key_not_a_variant",
                {"multivariate": _multivariate(("a", 100)), "payloads": {"b": "1"}},
                ["cross_field.payload_key_not_a_variant"],
            ),
            (
                "boolean_payload_key_not_true",
                {"payloads": {"false": "1"}},
                ["cross_field.payload_key_not_true"],
            ),
            ("boolean_payload_key_true", {"payloads": {"true": "1"}}, []),
            (
                "group_variant_not_a_variant",
                {"multivariate": _multivariate(("a", 100)), "groups": [{"variant": "b"}]},
                ["cross_field.group_variant_not_a_variant"],
            ),
            ("group_variant_empty_string_ignored", {"groups": [{"variant": ""}]}, []),
            (
                "person_aggregation_with_group_property",
                {"groups": [{"properties": [{"key": "k", "type": "group", "group_type_index": 0}]}]},
                ["cross_field.person_aggregation_property_type"],
            ),
            (
                "flag_level_aggregation_fallback_applies",
                {"aggregation_group_type_index": 0, "groups": [{"properties": [_person_prop()]}]},
                ["cross_field.group_aggregation_property_type"],
            ),
            (
                "explicit_null_aggregation_overrides_flag_level",
                {
                    "aggregation_group_type_index": 0,
                    "groups": [{"aggregation_group_type_index": None, "properties": [_person_prop()]}],
                },
                [],
            ),
            (
                "group_property_type_index_mismatch",
                {
                    "groups": [
                        {
                            "aggregation_group_type_index": 1,
                            "properties": [{"key": "k", "type": "group", "group_type_index": 0, "value": "x"}],
                        }
                    ]
                },
                ["cross_field.group_property_type_index_mismatch"],
            ),
            (
                "group_property_type_index_match",
                {
                    "groups": [
                        {
                            "aggregation_group_type_index": 1,
                            "properties": [
                                {"key": "k", "type": "group", "group_type_index": 1, "operator": "exact", "value": "x"}
                            ],
                        }
                    ]
                },
                [],
            ),
            (
                "flag_property_wrong_operator",
                {"groups": [{"properties": [{"key": "1", "type": "flag", "operator": "exact", "value": True}]}]},
                ["cross_field.flag_property_requires_flag_evaluates_to"],
            ),
            (
                "flag_property_correct_operator",
                {
                    "groups": [
                        {"properties": [{"key": "1", "type": "flag", "operator": "flag_evaluates_to", "value": True}]}
                    ]
                },
                [],
            ),
            (
                "in_operator_on_person_property",
                {"groups": [{"properties": [_person_prop(operator="in", value=[1])]}]},
                ["cross_field.in_not_in_requires_cohort"],
            ),
            (
                "in_operator_on_cohort_property",
                {"groups": [{"properties": [{"key": "id", "type": "cohort", "operator": "in", "value": 5}]}]},
                [],
            ),
            (
                "date_operator_unparseable_value",
                {"groups": [{"properties": [_person_prop(operator="is_date_after", value="not a date")]}]},
                ["cross_field.date_value_not_parseable"],
            ),
            (
                "date_operator_relative_value",
                {"groups": [{"properties": [_person_prop(operator="is_date_after", value="-30d")]}]},
                [],
            ),
            (
                "date_operator_iso_value",
                {"groups": [{"properties": [_person_prop(operator="is_date_exact", value="2024-01-01")]}]},
                [],
            ),
            (
                "regex_operator_numeric_value",
                {"groups": [{"properties": [_person_prop(operator="regex", value=5)]}]},
                ["cross_field.operator_requires_string_value"],
            ),
            (
                "gt_operator_numeric_value",
                {"groups": [{"properties": [_person_prop(operator="gt", value=5)]}]},
                ["cross_field.operator_requires_string_value"],
            ),
            (
                "multi_contains_string_value",
                {"groups": [{"properties": [_person_prop(operator="icontains_multi", value="a")]}]},
                ["cross_field.operator_requires_list_value"],
            ),
            (
                "multi_contains_list_value",
                {"groups": [{"properties": [_person_prop(operator="icontains_multi", value=["a"])]}]},
                [],
            ),
            (
                "semver_invalid_value",
                {"groups": [{"properties": [_person_prop(operator="semver_gt", value="abc")]}]},
                ["cross_field.semver_value_invalid"],
            ),
            (
                "semver_valid_value",
                {"groups": [{"properties": [_person_prop(operator="semver_gt", value="1.2.3")]}]},
                [],
            ),
            (
                "semver_wildcard_value",
                {"groups": [{"properties": [_person_prop(operator="semver_wildcard", value="1.2.*")]}]},
                [],
            ),
            (
                "semver_non_string_value",
                {"groups": [{"properties": [_person_prop(operator="semver_eq", value=123)]}]},
                ["cross_field.semver_value_invalid"],
            ),
            (
                "starts_with_string_value",
                {"groups": [{"properties": [_person_prop(operator="starts_with", value="posthog")]}]},
                [],
            ),
            (
                "starts_with_numeric_value",
                {"groups": [{"properties": [_person_prop(operator="starts_with", value=123)]}]},
                ["cross_field.operator_requires_string_value"],
            ),
            (
                "not_starts_with_string_value",
                {"groups": [{"properties": [_person_prop(operator="not_starts_with", value="posthog")]}]},
                [],
            ),
            (
                "ends_with_string_value",
                {"groups": [{"properties": [_person_prop(operator="ends_with", value=".com")]}]},
                [],
            ),
            (
                "not_ends_with_string_value",
                {"groups": [{"properties": [_person_prop(operator="not_ends_with", value=".com")]}]},
                [],
            ),
        ]
    )
    def test_cross_field_rules(self, _name: str, filters: dict[str, Any], expected_rule_ids: list[str]) -> None:
        violations = collect_cross_field_violations(filters)
        assert sorted(violation.rule_id for violation in violations) == sorted(expected_rule_ids), violations

    def test_violation_paths_preserve_indices(self) -> None:
        filters = {
            "groups": [
                {"properties": []},
                {"properties": [_person_prop(), _person_prop(operator="regex", value=5)]},
            ]
        }
        violations = collect_cross_field_violations(filters)
        assert [violation.path for violation in violations] == ["groups[1].properties[1].value"]

    # Validated filters are stored and then served verbatim to SDKs, and the .NET and Java
    # clients type rollout percentages as int, so 100 must not come back as 100.0.
    @parameterized.expand(
        [
            ("int_stays_int", 100, 100, int),
            ("whole_float_narrows_to_int", 100.0, 100, int),
            ("fraction_stays_float", 33.33, 33.33, float),
            ("zero_stays_int", 0, 0, int),
        ]
    )
    def test_rollout_percentage_keeps_whole_numbers_as_ints(
        self, _name: str, stored: float, expected: float, expected_type: type
    ) -> None:
        serializer = FeatureFlagFiltersSerializer(
            data={
                "groups": [{"properties": [], "rollout_percentage": stored, "variant": None}],
                "multivariate": _multivariate(("a", stored)),
            },
            context={},
        )

        assert serializer.is_valid(), serializer.errors
        group_rollout = serializer.validated_data["groups"][0]["rollout_percentage"]
        variant_rollout = serializer.validated_data["multivariate"]["variants"][0]["rollout_percentage"]
        assert group_rollout == expected
        assert type(group_rollout) is expected_type
        assert type(variant_rollout) is expected_type

    def test_flatten_structural_errors_strips_indices_in_rule_id(self) -> None:
        errors = {
            "groups": [
                {},
                {"properties": [{}, {"key": [ErrorDetail("This field is required.", code="required")]}]},
            ]
        }
        violations = flatten_structural_errors(errors)
        assert violations == [
            Violation(
                rule_id="structural.groups[].properties[].key.required",
                path="groups[1].properties[1].key",
                message="This field is required.",
            )
        ]

    def test_flatten_structural_errors_handles_non_field_errors_and_int_keys(self) -> None:
        errors = {
            "groups": {
                "non_field_errors": [ErrorDetail('Expected a list of items but got type "str".', code="not_a_list")]
            },
            "payloads": {0: [ErrorDetail("bad", code="invalid")]},
        }
        rule_ids = {violation.rule_id for violation in flatten_structural_errors(errors)}
        assert rule_ids == {"structural.groups.not_a_list", "structural.payloads[].invalid"}

    @parameterized.expand([("none", None), ("list", []), ("string", "x")])
    def test_non_dict_filters_reported(self, _name: str, filters: Any) -> None:
        violations = collect_filters_violations(filters)
        assert [violation.rule_id for violation in violations] == ["structural.filters.not_a_dict"]

    def test_structural_failure_short_circuits_cross_field(self) -> None:
        filters = {
            "multivariate": _multivariate(("a", 50)),
            "payloads": {"b": "not json"},
        }
        rule_ids = [violation.rule_id for violation in collect_filters_violations(filters)]
        assert rule_ids == ["structural.payloads.invalid_payload_json"]

    def test_variant_rollout_sum_violation_message_hides_float_artifacts(self) -> None:
        violations = check_variant_rollout_sum({"multivariate": _multivariate(("a", 0.01), ("b", 64.04), ("c", 35))})

        assert violations[0].message == "Variant rollout percentages must sum to 100, got 99.05."

    def test_collect_filters_violations_end_to_end(self) -> None:
        structural = collect_filters_violations({"groups": [{"properties": [{"type": "person"}]}]})
        assert [violation.rule_id for violation in structural] == ["structural.groups[].properties[].key.required"]

        cross_field = collect_filters_violations({"multivariate": _multivariate(("a", 50))})
        assert [violation.rule_id for violation in cross_field] == ["cross_field.variant_rollout_sum_not_100"]

    def test_groups_non_empty_is_a_create_only_rule(self) -> None:
        # The POST/PATCH asymmetry is locked on #50084: stored/patched flags may have empty
        # groups, so the rule must stay out of CROSS_FIELD_CHECKS (and out of the audit).
        assert check_groups_non_empty_for_create not in CROSS_FIELD_CHECKS
        assert collect_cross_field_violations({"groups": []}) == []
        assert [violation.rule_id for violation in check_groups_non_empty_for_create({"groups": []})] == [
            "contextual.groups_empty_on_create"
        ]
        assert check_groups_non_empty_for_create({"groups": [{"properties": []}]}) == []


class TestRejectSerdeUnsafeFilters(SimpleTestCase):
    # The only cache-poisoning guard that runs while the enforcement switch is off, and the
    # structural tier shadows it once the switch is on, so it needs its own coverage: nothing
    # else in the suite exercises these rules.
    @parameterized.expand(
        [
            ("filters_not_dict", "not a dict"),
            ("agg_index_bool", {"aggregation_group_type_index": True}),
            ("agg_index_string", {"aggregation_group_type_index": "0"}),
            ("agg_index_over_i32", {"aggregation_group_type_index": 2**31}),
            ("early_exit_int", {"early_exit": 1}),
            ("feature_enrollment_string", {"feature_enrollment": "true"}),
            ("holdout_not_dict", {"holdout": []}),
            ("holdout_id_missing", {"holdout": {"exclusion_percentage": 10}}),
            ("holdout_id_over_i64", {"holdout": {"id": 2**63, "exclusion_percentage": 10}}),
            ("holdout_exclusion_missing", {"holdout": {"id": 1}}),
            ("holdout_exclusion_string", {"holdout": {"id": 1, "exclusion_percentage": "10"}}),
            ("groups_not_list", {"groups": {}}),
            ("group_not_dict", {"groups": ["x"]}),
            ("group_variant_int", {"groups": [{"variant": 1}]}),
            ("group_rollout_string", {"groups": [{"rollout_percentage": "50"}]}),
            ("group_rollout_bool", {"groups": [{"rollout_percentage": True}]}),
            ("group_rollout_nan", {"groups": [{"rollout_percentage": float("nan")}]}),
            ("group_rollout_over_100", {"groups": [{"rollout_percentage": 150}]}),
            ("group_agg_index_bool", {"groups": [{"aggregation_group_type_index": False}]}),
            ("group_agg_index_under_i32", {"groups": [{"aggregation_group_type_index": -(2**31) - 1}]}),
            ("properties_not_list", {"groups": [{"properties": {}}]}),
            ("property_not_dict", {"groups": [{"properties": ["x"]}]}),
            ("property_group_type_index_string", {"groups": [{"properties": [{"group_type_index": "1"}]}]}),
            ("property_group_type_index_over_i32", {"groups": [{"properties": [{"group_type_index": 2**31}]}]}),
            ("property_negation_string", {"groups": [{"properties": [{"negation": "false"}]}]}),
            ("property_operator_unknown", {"groups": [{"properties": [{"operator": "does not equal"}]}]}),
            ("property_operator_unhashable", {"groups": [{"properties": [{"operator": []}]}]}),
            ("property_type_unknown", {"groups": [{"properties": [{"key": "k", "type": "banana"}]}]}),
            ("property_type_not_string", {"groups": [{"properties": [{"key": "k", "type": 1}]}]}),
            # Rust has no `event` variant, so one of these fails the team's whole cached set.
            ("property_type_event", {"groups": [{"properties": [{"key": "k", "type": "event"}]}]}),
            # `behavioral` is a real insight filter type, but Rust flag matching has no variant
            # for it (it can't evaluate events history) — it must stay rejected here.
            ("property_type_behavioral", {"groups": [{"properties": [{"key": "$pageview", "type": "behavioral"}]}]}),
            ("property_type_missing", {"groups": [{"properties": [{"key": "k"}]}]}),
            ("property_empty", {"groups": [{"properties": [{}]}]}),
            ("property_key_missing", {"groups": [{"properties": [{"type": "person"}]}]}),
            ("property_key_null", {"groups": [{"properties": [{"key": None, "type": "person"}]}]}),
            ("property_key_bool", {"groups": [{"properties": [{"key": True, "type": "person"}]}]}),
            ("property_key_list", {"groups": [{"properties": [{"key": [], "type": "person"}]}]}),
            ("multivariate_not_dict", {"multivariate": []}),
            ("multivariate_variants_missing", {"multivariate": {}}),
            ("multivariate_variants_null", {"multivariate": {"variants": None}}),
            ("variants_not_list", {"multivariate": {"variants": {}}}),
            ("variant_not_dict", {"multivariate": {"variants": ["x"]}}),
            ("variant_rollout_null", {"multivariate": {"variants": [{"key": "a", "rollout_percentage": None}]}}),
            ("variant_key_missing", {"multivariate": {"variants": [{"rollout_percentage": 100}]}}),
            ("variant_key_not_string", {"multivariate": {"variants": [{"key": 1, "rollout_percentage": 100}]}}),
            (
                "variant_name_not_string",
                {"multivariate": {"variants": [{"key": "a", "name": 1, "rollout_percentage": 100}]}},
            ),
            ("payloads_not_dict", {"payloads": []}),
            ("payload_string_not_json", {"payloads": {"true": "not json"}}),
        ]
    )
    def test_rejects_what_poisons_the_flag_cache(self, _name: str, filters: Any) -> None:
        with self.assertRaises(serializers.ValidationError):
            _reject_serde_unsafe_filters(filters)

    @parameterized.expand(
        [
            ("empty", {}),
            ("alias_operator", {"groups": [{"properties": [{"key": "k", "type": "person", "operator": "min"}]}]}),
            # Rust deserializes person_metadata; the structural tier narrows to four types,
            # but that is a policy choice rather than something serde rejects.
            ("person_metadata_type", {"groups": [{"properties": [{"key": "k", "type": "person_metadata"}]}]}),
            ("operator_absent", {"groups": [{"properties": [{"key": "x", "type": "person"}]}]}),
            # deserialize_key accepts a JSON number and normalizes it to a string.
            ("numeric_key", {"groups": [{"properties": [{"key": 226357, "type": "flag"}]}]}),
            ("payload_dict_value", {"payloads": {"true": {"a": 1}}}),
            ("payload_nan_token", {"payloads": {"true": "NaN"}}),
            ("redacted_payload_sentinel", {"payloads": {"true": REDACTED_PAYLOAD_VALUE}}),
            ("holdout_exclusion_clamped_by_rust", {"holdout": {"id": 1, "exclusion_percentage": 150}}),
            (
                "well_formed",
                {
                    "groups": [
                        {
                            "properties": [{"key": "email", "type": "person", "operator": "icontains", "value": "@x"}],
                            "rollout_percentage": 50,
                        }
                    ],
                    "multivariate": {"variants": [{"key": "a", "rollout_percentage": 100}]},
                    "payloads": {"a": '"p"'},
                    "feature_enrollment": False,
                    "holdout": {"id": 1, "exclusion_percentage": 10},
                },
            ),
        ]
    )
    def test_accepts_what_master_accepted(self, _name: str, filters: Any) -> None:
        _reject_serde_unsafe_filters(filters)
