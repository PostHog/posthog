from copy import deepcopy
from typing import Any

import pytest

from parameterized import parameterized

from products.feature_flags.backend.facade.config import (
    ConfigFormat,
    ConfigFormatError,
    ConfigV2,
    RuleV2,
    detect_config_format,
    parse_v2_config,
)

# Shapes from the Feature Flag Rules v2 contract fixtures; identifiers are invented.
V2_BOOLEAN_ALL_RULE_TYPES: dict[str, Any] = {
    "version": 2,
    "return_type": "boolean",
    "default_value": False,
    "rules": [
        {
            "id": "11111111-1111-4111-8111-111111111111",
            "rule_type": "targeted_release",
            "targeting": {
                "properties": [
                    {
                        "key": "account_tier",
                        "type": "person",
                        "operator": "exact",
                        "value": "preview",
                        "label": "Account tier",
                    }
                ]
            },
            "description": "Enable the preview for selected accounts.",
            "metadata": {"display_color": "blue"},
            "value": True,
        },
        {
            "id": "22222222-2222-4222-8222-222222222222",
            "rule_type": "percentage_rollout",
            "targeting": {"properties": []},
            "value": True,
            "rollout_percentage": 25.5,
            "on_rollout_miss": "continue",
            "assignment_algorithm": "sha1_60_v1",
            "seed": "release-preview",
            "assign_by": "person",
        },
        {
            "id": "44444444-4444-4444-8444-444444444444",
            "rule_type": "experiment",
            "targeting": {"properties": []},
            "experiment_id": 42,
            "paused": False,
            "rollout_percentage": 100,
            "on_rollout_miss": "continue",
            "assignment_algorithm": "sha1_60_v1",
            "seed": "experiment-preview",
            "assign_by": "person",
            "variants": [
                {"key": "control", "weight": 50, "value": True},
                {"key": "test", "weight": 50, "value": True},
            ],
            "holdout": {"id": 7, "seed": "holdout-", "exclusion_percentage": 5},
        },
    ],
}

V2_STRING_GROUP_ASSIGNMENT: dict[str, Any] = {
    "version": 2,
    "return_type": "string",
    "default_value": "standard",
    "aggregation_group_type_index": 0,
    "rules": [
        {
            "id": "55555555-5555-4555-8555-555555555555",
            "rule_type": "percentage_rollout",
            "targeting": {
                "properties": [
                    {
                        "key": "region",
                        "type": "group",
                        "operator": "exact",
                        "value": "north",
                        "group_type_index": 0,
                        "group_key_names": {"organization": "Organization"},
                    }
                ]
            },
            "value": "compact",
            "rollout_percentage": 50,
            "on_rollout_miss": "continue",
            "assignment_algorithm": "sha1_60_v1",
            "seed": "group-release",
        }
    ],
}


class TestDetectConfigFormat:
    @parameterized.expand(
        [
            ("absent_version", {"groups": []}, ConfigFormat(kind="v1", raw_version=None)),
            ("empty_filters", {}, ConfigFormat(kind="v1", raw_version=None)),
            ("none_filters", None, ConfigFormat(kind="v1", raw_version=None)),
            ("version_1", {"version": 1}, ConfigFormat(kind="v1", raw_version=1)),
            ("version_1_float", {"version": 1.0}, ConfigFormat(kind="v1", raw_version=1.0)),
            ("version_2", {"version": 2}, ConfigFormat(kind="v2", raw_version=2)),
            ("version_2_float", {"version": 2.0}, ConfigFormat(kind="v2", raw_version=2.0)),
            ("version_true_is_not_1", {"version": True}, ConfigFormat(kind="unsupported", raw_version=True)),
            ("version_string", {"version": "2"}, ConfigFormat(kind="unsupported", raw_version="2")),
            ("version_null", {"version": None}, ConfigFormat(kind="unsupported", raw_version=None)),
            ("unknown_future_version", {"version": 3}, ConfigFormat(kind="unsupported", raw_version=3)),
            ("fractional_version", {"version": 1.5}, ConfigFormat(kind="unsupported", raw_version=1.5)),
        ]
    )
    def test_detection(self, _name, filters, expected):
        assert detect_config_format(filters) == expected


class TestParseV2Config:
    def test_boolean_document_with_every_rule_type(self):
        assert parse_v2_config(V2_BOOLEAN_ALL_RULE_TYPES) == ConfigV2(
            return_type="boolean",
            default_value=False,
            rules=(
                RuleV2(id="11111111-1111-4111-8111-111111111111", rule_type="targeted_release", experiment_id=None),
                RuleV2(id="22222222-2222-4222-8222-222222222222", rule_type="percentage_rollout", experiment_id=None),
                RuleV2(
                    id="44444444-4444-4444-8444-444444444444",
                    rule_type="experiment",
                    experiment_id=42,
                ),
            ),
            aggregation_group_type_index=None,
        )

    def test_string_group_document(self):
        assert parse_v2_config(V2_STRING_GROUP_ASSIGNMENT) == ConfigV2(
            return_type="string",
            default_value="standard",
            rules=(
                RuleV2(id="55555555-5555-4555-8555-555555555555", rule_type="percentage_rollout", experiment_id=None),
            ),
            aggregation_group_type_index=0,
        )

    def test_float_version_literal_selects_v2(self):
        assert parse_v2_config(
            {"version": 2.0, "return_type": "boolean", "default_value": None, "rules": []}
        ) == ConfigV2(return_type="boolean", default_value=None, rules=(), aggregation_group_type_index=None)

    @parameterized.expand(
        [
            ("v1_document", {"groups": [{"properties": [], "rollout_percentage": 100}]}, "v1"),
            ("version_string", {**V2_BOOLEAN_ALL_RULE_TYPES, "version": "2"}, "unsupported"),
            ("unknown_future_version", {**V2_BOOLEAN_ALL_RULE_TYPES, "version": 3}, "unsupported"),
            ("untrusted_version", {**V2_BOOLEAN_ALL_RULE_TYPES, "version": "<untrusted-version>"}, "unsupported"),
        ]
    )
    def test_non_v2_formats_are_rejected(self, _name, filters, expected_kind):
        with pytest.raises(ConfigFormatError) as exc_info:
            parse_v2_config(filters)
        assert exc_info.value.config_format.kind == expected_kind
        assert exc_info.value.config_format.raw_version == filters.get("version")
        assert str(exc_info.value) == f"config format {expected_kind!r} is not handled here"

    @parameterized.expand(
        [
            ("return_type", None, "return_type"),
            ("default_value", None, "default_value"),
            ("rules", None, "rules"),
            ("rule_id", 0, "id"),
            ("rule_type", 0, "rule_type"),
            ("experiment_id", 2, "experiment_id"),
        ]
    )
    def test_missing_required_keys_are_rejected(self, _name: str, rule_index: int | None, key: str) -> None:
        filters = deepcopy(V2_BOOLEAN_ALL_RULE_TYPES)
        target = filters if rule_index is None else filters["rules"][rule_index]
        del target[key]

        with pytest.raises(KeyError) as exc_info:
            parse_v2_config(filters)
        assert exc_info.value.args == (key,)

    @parameterized.expand(
        [
            ("unknown_return_type", "return_type", "future_return_type", "Unsupported feature flag return type"),
            ("null_return_type", "return_type", None, "Unsupported feature flag return type"),
            ("removed_rule_type", "rule_type", "variant_rollout", "Unsupported feature flag rule type"),
            ("null_rule_type", "rule_type", None, "Unsupported feature flag rule type"),
        ]
    )
    def test_unsupported_types_are_rejected(self, _name: str, key: str, value: object, message: str) -> None:
        filters = deepcopy(V2_BOOLEAN_ALL_RULE_TYPES)
        target = filters if key == "return_type" else filters["rules"][0]
        target[key] = value

        with pytest.raises(ValueError, match=message):
            parse_v2_config(filters)
