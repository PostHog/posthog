import copy
from types import SimpleNamespace
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail

from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer
from products.feature_flags.backend.filters_validation import (
    CROSS_FIELD_CHECKS,
    Violation,
    check_groups_non_empty_for_create,
    collect_cross_field_violations,
    collect_filters_violations,
    flatten_structural_errors,
    validate_cross_field_or_raise,
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

    def test_collect_filters_violations_end_to_end(self) -> None:
        structural = collect_filters_violations({"groups": [{"properties": [{"type": "person"}]}]})
        assert [violation.rule_id for violation in structural] == ["structural.groups[].properties[].key.required"]

        cross_field = collect_filters_violations({"multivariate": _multivariate(("a", 50))})
        assert [violation.rule_id for violation in cross_field] == ["cross_field.variant_rollout_sum_not_100"]

    def test_validate_cross_field_or_raise(self) -> None:
        validate_cross_field_or_raise({"groups": []})

        with self.assertRaises(serializers.ValidationError) as ctx:
            validate_cross_field_or_raise({"multivariate": _multivariate(("a", 50))})
        detail = ctx.exception.detail
        assert isinstance(detail, list) and isinstance(detail[0], ErrorDetail)
        assert detail[0].code == "cross_field.variant_rollout_sum_not_100"

    # Parity guard for the phases 1-2 window: the cross-field rules mirror logic that still
    # lives in validate_filters, and both run independently until the phase 3 swap. This
    # corpus exercises the mirrored rules through both paths and asserts the same
    # accept/reject verdict, so an edit to either side that changes a shared rule fails here
    # instead of silently making the audit measure a different rule set than the write path.
    # Scope: only rules that exist on both sides, with structurally valid input, and no
    # cohort/flag properties or early_exit (those branches of validate_filters need DB or
    # org context). Message text and error codes are documented to differ.
    @parameterized.expand(
        [
            ("variant_sum_100_accepted", {"groups": [{}], "multivariate": _multivariate(("a", 50), ("b", 50))}, True),
            ("variant_sum_50_rejected", {"groups": [{}], "multivariate": _multivariate(("a", 50))}, False),
            (
                "variant_override_valid",
                {"groups": [{"variant": "a"}], "multivariate": _multivariate(("a", 100))},
                True,
            ),
            (
                "variant_override_dangling",
                {"groups": [{"variant": "b"}], "multivariate": _multivariate(("a", 100))},
                False,
            ),
            ("in_on_person_rejected", {"groups": [{"properties": [_person_prop(operator="in", value=[1])]}]}, False),
            (
                "regex_string_accepted",
                {"groups": [{"properties": [_person_prop(operator="regex", value="^a+$")]}]},
                True,
            ),
            ("regex_numeric_rejected", {"groups": [{"properties": [_person_prop(operator="regex", value=5)]}]}, False),
            ("gt_string_accepted", {"groups": [{"properties": [_person_prop(operator="gt", value="5")]}]}, True),
            ("gt_numeric_rejected", {"groups": [{"properties": [_person_prop(operator="gt", value=5)]}]}, False),
            (
                "min_alias_string_accepted",
                {"groups": [{"properties": [_person_prop(operator="min", value="5")]}]},
                True,
            ),
            (
                "date_relative_accepted",
                {"groups": [{"properties": [_person_prop(operator="is_date_after", value="-30d")]}]},
                True,
            ),
            (
                "date_junk_rejected",
                {"groups": [{"properties": [_person_prop(operator="is_date_after", value="not a date")]}]},
                False,
            ),
            (
                "semver_valid_accepted",
                {"groups": [{"properties": [_person_prop(operator="semver_gt", value="1.2.3")]}]},
                True,
            ),
            (
                "semver_junk_rejected",
                {"groups": [{"properties": [_person_prop(operator="semver_gt", value="abc")]}]},
                False,
            ),
            (
                "multi_contains_list_accepted",
                {"groups": [{"properties": [_person_prop(operator="icontains_multi", value=["a"])]}]},
                True,
            ),
            (
                "multi_contains_string_rejected",
                {"groups": [{"properties": [_person_prop(operator="icontains_multi", value="a")]}]},
                False,
            ),
            (
                "person_agg_group_property_rejected",
                {"groups": [{"properties": [{"key": "k", "type": "group", "group_type_index": 0, "value": "x"}]}]},
                False,
            ),
            (
                "group_agg_matching_index_accepted",
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
                True,
            ),
            (
                "payload_key_not_variant_rejected",
                {"groups": [{}], "multivariate": _multivariate(("a", 100)), "payloads": {"b": "1"}},
                False,
            ),
            ("boolean_payload_false_key_rejected", {"groups": [{}], "payloads": {"false": "1"}}, False),
            ("empty_groups_rejected_on_create", {"groups": []}, False),
        ]
    )
    def test_write_path_parity(self, _name: str, filters: dict[str, Any], expected_accept: bool) -> None:
        live_serializer = FeatureFlagSerializer(
            data={}, context={"request": SimpleNamespace(method="POST"), "project_id": 1}
        )
        try:
            live_serializer.validate_filters(copy.deepcopy(filters))
            live_accepts = True
        except serializers.ValidationError:
            live_accepts = False

        working = copy.deepcopy(filters)
        violations = collect_filters_violations(working) or check_groups_non_empty_for_create(working)
        new_accepts = not violations

        assert live_accepts == expected_accept
        assert new_accepts == expected_accept, violations

    def test_groups_non_empty_is_a_create_only_rule(self) -> None:
        # The POST/PATCH asymmetry is locked on #50084: stored/patched flags may have empty
        # groups, so the rule must stay out of CROSS_FIELD_CHECKS (and out of the audit).
        assert check_groups_non_empty_for_create not in CROSS_FIELD_CHECKS
        assert collect_cross_field_violations({"groups": []}) == []
        assert [violation.rule_id for violation in check_groups_non_empty_for_create({"groups": []})] == [
            "contextual.groups_empty_on_create"
        ]
        assert check_groups_non_empty_for_create({"groups": [{"properties": []}]}) == []
