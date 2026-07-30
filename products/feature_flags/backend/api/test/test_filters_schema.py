from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.feature_flags.backend.api.filters_schema import (
    FeatureFlagFiltersSerializer,
    FlagConditionGroupSerializer,
    FlagPropertySerializer,
)

VALID_PROPERTY: dict[str, Any] = {"key": "email", "type": "person", "operator": "icontains", "value": "@posthog.com"}

KITCHEN_SINK_FILTERS: dict[str, Any] = {
    "groups": [
        {
            "properties": [{**VALID_PROPERTY, "negation": False, "group_type_index": None}],
            "rollout_percentage": 50.0,
            "variant": "control",
            "aggregation_group_type_index": None,
        },
        {"properties": [], "rollout_percentage": None},
    ],
    "multivariate": {
        "variants": [
            {"key": "control", "name": "Control", "rollout_percentage": 50},
            {"key": "test", "rollout_percentage": 50},
        ]
    },
    "aggregation_group_type_index": None,
    "payloads": {"control": '{"plan": "pro"}'},
    "feature_enrollment": True,
    "holdout": {"id": 5, "exclusion_percentage": 10.0},
    "early_exit": False,
}


def _codes_under(node: Any) -> set[str]:
    if isinstance(node, dict):
        return {code for child in node.values() for code in _codes_under(child)}
    if isinstance(node, list):
        return {code for child in node for code in _codes_under(child)}
    return {getattr(node, "code", None) or "invalid"}


class TestFiltersSchema(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty", {}),
            ("empty_groups", {"groups": []}),
            ("kitchen_sink", KITCHEN_SINK_FILTERS),
            ("null_optionals", {"groups": [], "multivariate": None, "holdout": None, "early_exit": None}),
            ("null_payloads", {"payloads": None}),
            ("null_group_properties", {"groups": [{"properties": None, "rollout_percentage": 50}]}),
        ]
    )
    def test_valid_filters_pass(self, _name: str, filters: dict[str, Any]) -> None:
        serializer = FeatureFlagFiltersSerializer(data=filters)
        assert serializer.is_valid(), serializer.errors

    @parameterized.expand(
        [
            ("groups_not_a_list", {"groups": "all"}, ["groups"], "not_a_list"),
            ("group_not_a_dict", {"groups": ["x"]}, ["groups", 0], "invalid"),
            ("property_key_missing", {"groups": [{"properties": [{"type": "person"}]}]}, ["groups"], "required"),
            (
                "property_key_blank",
                {"groups": [{"properties": [{"key": "", "type": "person"}]}]},
                ["groups"],
                "blank",
            ),
            (
                "property_key_bool",
                {"groups": [{"properties": [{"key": True, "type": "person"}]}]},
                ["groups"],
                "invalid",
            ),
            (
                "property_key_list",
                {"groups": [{"properties": [{"key": ["a"], "type": "person"}]}]},
                ["groups"],
                "invalid",
            ),
            ("property_type_missing", {"groups": [{"properties": [{"key": "k"}]}]}, ["groups"], "required"),
            (
                "property_type_unknown",
                {"groups": [{"properties": [{"key": "k", "type": "event"}]}]},
                ["groups"],
                "invalid_choice",
            ),
            (
                "property_type_person_metadata",
                {"groups": [{"properties": [{"key": "k", "type": "person_metadata"}]}]},
                ["groups"],
                "invalid_choice",
            ),
            (
                "property_operator_unknown",
                {"groups": [{"properties": [{**VALID_PROPERTY, "operator": "bogus"}]}]},
                ["groups"],
                "invalid_choice",
            ),
            (
                "property_operator_unhashable_list",
                {"groups": [{"properties": [{**VALID_PROPERTY, "operator": []}]}]},
                ["groups"],
                "invalid_choice",
            ),
            (
                "property_operator_unhashable_dict",
                {"groups": [{"properties": [{**VALID_PROPERTY, "operator": {}}]}]},
                ["groups"],
                "invalid_choice",
            ),
            (
                "property_group_type_index_string",
                {"groups": [{"properties": [{**VALID_PROPERTY, "group_type_index": "0"}]}]},
                ["groups"],
                "invalid",
            ),
            (
                "property_group_type_index_float",
                {"groups": [{"properties": [{**VALID_PROPERTY, "group_type_index": 1.5}]}]},
                ["groups"],
                "invalid",
            ),
            (
                "property_group_type_index_bool",
                {"groups": [{"properties": [{**VALID_PROPERTY, "group_type_index": True}]}]},
                ["groups"],
                "invalid",
            ),
            (
                "property_negation_int",
                {"groups": [{"properties": [{**VALID_PROPERTY, "negation": 1}]}]},
                ["groups"],
                "invalid",
            ),
            ("group_rollout_negative", {"groups": [{"rollout_percentage": -1}]}, ["groups"], "min_value"),
            ("group_rollout_over_100", {"groups": [{"rollout_percentage": 101}]}, ["groups"], "max_value"),
            ("group_rollout_string", {"groups": [{"rollout_percentage": "50"}]}, ["groups"], "invalid"),
            ("group_rollout_bool", {"groups": [{"rollout_percentage": True}]}, ["groups"], "invalid"),
            ("group_rollout_nan", {"groups": [{"rollout_percentage": float("nan")}]}, ["groups"], "invalid"),
            ("group_variant_numeric", {"groups": [{"variant": 123}]}, ["groups"], "invalid"),
            ("group_aggregation_string", {"groups": [{"aggregation_group_type_index": "0"}]}, ["groups"], "invalid"),
            (
                "group_aggregation_i32_overflow",
                {"groups": [{"aggregation_group_type_index": 2**31}]},
                ["groups"],
                "max_value",
            ),
            (
                "property_group_type_index_i32_underflow",
                {"groups": [{"properties": [{**VALID_PROPERTY, "group_type_index": -(2**31) - 1}]}]},
                ["groups"],
                "min_value",
            ),
            ("multivariate_missing_variants", {"multivariate": {}}, ["multivariate"], "required"),
            ("multivariate_empty_variants", {"multivariate": {"variants": []}}, ["multivariate"], "empty"),
            (
                "variant_key_blank",
                {"multivariate": {"variants": [{"key": "", "rollout_percentage": 100}]}},
                ["multivariate"],
                "blank",
            ),
            (
                "variant_key_numeric",
                {"multivariate": {"variants": [{"key": 5, "rollout_percentage": 100}]}},
                ["multivariate"],
                "invalid",
            ),
            ("variant_rollout_missing", {"multivariate": {"variants": [{"key": "a"}]}}, ["multivariate"], "required"),
            (
                "variant_rollout_null",
                {"multivariate": {"variants": [{"key": "a", "rollout_percentage": None}]}},
                ["multivariate"],
                "null",
            ),
            (
                "variant_rollout_string",
                {"multivariate": {"variants": [{"key": "a", "rollout_percentage": "100"}]}},
                ["multivariate"],
                "invalid",
            ),
            ("holdout_missing_id", {"holdout": {"exclusion_percentage": 10}}, ["holdout"], "required"),
            ("holdout_id_string", {"holdout": {"id": "5", "exclusion_percentage": 10}}, ["holdout"], "invalid"),
            (
                "holdout_id_i64_overflow",
                {"holdout": {"id": 2**63, "exclusion_percentage": 10}},
                ["holdout"],
                "max_value",
            ),
            (
                "holdout_exclusion_over_100",
                {"holdout": {"id": 5, "exclusion_percentage": 150}},
                ["holdout"],
                "max_value",
            ),
            ("feature_enrollment_string", {"feature_enrollment": "true"}, ["feature_enrollment"], "invalid"),
            ("early_exit_int", {"early_exit": 1}, ["early_exit"], "invalid"),
            (
                "aggregation_group_type_index_float",
                {"aggregation_group_type_index": 1.5},
                ["aggregation_group_type_index"],
                "invalid",
            ),
            (
                "aggregation_group_type_index_i32_overflow",
                {"aggregation_group_type_index": 2**31},
                ["aggregation_group_type_index"],
                "max_value",
            ),
            ("payloads_not_a_dict", {"payloads": []}, ["payloads"], "not_a_dict"),
            ("payload_invalid_json_string", {"payloads": {"true": "not json"}}, ["payloads"], "invalid_payload_json"),
            ("payload_blank_string", {"payloads": {"true": ""}}, ["payloads"], "invalid_payload_json"),
            ("payload_nan_float", {"payloads": {"true": float("nan")}}, ["payloads"], "invalid_payload_json"),
            ("payload_nan_string", {"payloads": {"true": "NaN"}}, ["payloads"], "invalid_payload_json"),
            ("payload_infinity_string", {"payloads": {"true": "Infinity"}}, ["payloads"], "invalid_payload_json"),
        ]
    )
    def test_invalid_filters_rejected(
        self, _name: str, filters: dict[str, Any], error_path: list[Any], expected_code: str
    ) -> None:
        serializer = FeatureFlagFiltersSerializer(data=filters)
        assert not serializer.is_valid()
        node: Any = serializer.errors
        for step in error_path:
            assert step in node if isinstance(node, dict) else step < len(node), serializer.errors
            node = node[step]
        assert expected_code in _codes_under(node), serializer.errors

    @parameterized.expand([("min", "gte"), ("max", "lte")])
    def test_operator_aliases_are_canonicalized(self, alias: str, canonical: str) -> None:
        serializer = FlagPropertySerializer(data={**VALID_PROPERTY, "operator": alias, "value": "5"})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["operator"] == canonical

    @parameterized.expand([("int", 123, "123"), ("float", 1.5, "1.5")])
    def test_numeric_property_keys_normalized_to_strings(self, _name: str, key: Any, expected: str) -> None:
        # Mirrors Rust deserialize_key: stored numeric keys evaluate fine and must not be
        # rejected (nor 400 a read-modify-write PATCH echoing them back).
        serializer = FlagPropertySerializer(data={**VALID_PROPERTY, "key": key})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["key"] == expected

    @parameterized.expand(
        [
            ("dict", {"a": 1}, '{"a": 1}'),
            ("list", [1, 2], "[1, 2]"),
            ("number", 5, "5"),
            ("bool", True, "true"),
            ("null", None, "null"),
            ("string_passthrough", '{"a": 1}', '{"a": 1}'),
        ]
    )
    def test_payload_values_normalized_to_json_strings(self, _name: str, value: Any, expected: str) -> None:
        serializer = FeatureFlagFiltersSerializer(data={"payloads": {"true": value}})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["payloads"] == {"true": expected}

    def test_null_group_properties_normalized_to_empty_list(self) -> None:
        serializer = FlagConditionGroupSerializer(data={"properties": None})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["properties"] == []

    def test_group_aggregation_absent_vs_null_is_preserved(self) -> None:
        absent = FlagConditionGroupSerializer(data={"properties": []})
        assert absent.is_valid(), absent.errors
        assert "aggregation_group_type_index" not in absent.validated_data

        explicit_null = FlagConditionGroupSerializer(data={"properties": [], "aggregation_group_type_index": None})
        assert explicit_null.is_valid(), explicit_null.errors
        assert explicit_null.validated_data["aggregation_group_type_index"] is None

    @patch("products.feature_flags.backend.api.filters_schema.logger")
    def test_legacy_unknown_filter_keys_dropped_without_logging(self, mock_logger: Any) -> None:
        serializer = FeatureFlagFiltersSerializer(
            data={"groups": [], "holdout_groups": [], "super_groups": []}, context={"flag_id": 1}
        )
        assert serializer.is_valid(), serializer.errors
        assert "holdout_groups" not in serializer.validated_data
        assert "super_groups" not in serializer.validated_data
        mock_logger.warning.assert_not_called()

    @parameterized.expand(
        [
            ("filters", {"groups": [], "junk": 1}, ["junk"]),
            (
                "group",
                {"groups": [{"properties": [], "description": "x", "sort_key": "y"}]},
                [
                    "description",
                    "sort_key",
                ],
            ),
            ("property", {"groups": [{"properties": [{**VALID_PROPERTY, "cohort_name": "x"}]}]}, ["cohort_name"]),
            (
                "multivariate",
                {"multivariate": {"variants": [{"key": "a", "rollout_percentage": 100}], "junk_m": 1}},
                ["junk_m"],
            ),
            (
                "variant",
                {"multivariate": {"variants": [{"key": "a", "rollout_percentage": 100, "junk_v": 1}]}},
                ["junk_v"],
            ),
            ("holdout", {"holdout": {"id": 1, "exclusion_percentage": 0, "junk_h": 1}}, ["junk_h"]),
        ]
    )
    @patch("products.feature_flags.backend.api.filters_schema.logger")
    def test_non_legacy_unknown_keys_logged_per_level(
        self, level: str, filters: dict[str, Any], expected_keys: list[str], mock_logger: Any
    ) -> None:
        serializer = FeatureFlagFiltersSerializer(data=filters, context={"flag_id": 42})
        assert serializer.is_valid(), serializer.errors
        mock_logger.warning.assert_called_once_with(
            "feature_flag_filters_unknown_keys_dropped", level=level, keys=expected_keys, flag_id=42
        )

    @patch("products.feature_flags.backend.api.filters_schema.logger")
    def test_sink_collects_unknown_keys_instead_of_logging(self, mock_logger: Any) -> None:
        recorded: list[dict[str, Any]] = []

        class Sink:
            def record(self, *, level: str, keys: Any, flag_id: int | None) -> None:
                recorded.append({"level": level, "keys": list(keys), "flag_id": flag_id})

        serializer = FeatureFlagFiltersSerializer(
            data={"groups": [], "junk": 1, "holdout_groups": []},
            context={"unknown_keys_sink": Sink(), "flag_id": 7},
        )
        assert serializer.is_valid(), serializer.errors
        assert recorded == [{"level": "filters", "keys": ["holdout_groups", "junk"], "flag_id": 7}]
        mock_logger.warning.assert_not_called()
