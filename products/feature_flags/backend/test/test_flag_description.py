import json
from dataclasses import asdict, replace
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.feature_flags.backend.flag_description import ConditionShape, FlagDescription, describe_flag
from products.feature_flags.backend.models.feature_flag import FeatureFlag

FULL_PERSON_FLAG = FlagDescription(
    active=True,
    holdout=False,
    enrollment=False,
    multivariate=False,
    early_exit=False,
    evaluation_runtime="all",
    conditions=(ConditionShape(rollout=100.0, has_properties=False, aggregation=None),),
    variants=(),
)


def _flag(filters: dict[str, Any] | None, **fields: Any) -> FeatureFlag:
    return FeatureFlag(
        key="secret-launch",
        name="Secret launch",
        filters=filters,
        **{"active": True, "evaluation_runtime": "all", **fields},
    )


class TestDescribeFlag(SimpleTestCase):
    def test_description_keeps_the_shape_and_drops_every_value(self):
        flag = _flag(
            {
                "aggregation_group_type_index": 1,
                "groups": [
                    {
                        "properties": [
                            {"key": "email", "type": "person", "operator": "icontains", "value": "@example.com"}
                        ],
                        "rollout_percentage": 30,
                        "variant": "treatment",
                    },
                    {
                        "properties": [{"key": "id", "type": "cohort", "value": 4242}],
                        "aggregation_group_type_index": None,
                    },
                    {"properties": [], "rollout_percentage": 0},
                ],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control arm", "rollout_percentage": 60},
                        {"key": "treatment", "rollout_percentage": 40},
                    ]
                },
                "payloads": {"treatment": '{"token": "fake-payload-token"}'},
                "holdout": {"id": 3, "exclusion_percentage": 10},
                "feature_enrollment": True,
                "early_exit": True,
            }
        )

        description = describe_flag(flag)

        assert description == FlagDescription(
            active=True,
            holdout=True,
            enrollment=True,
            multivariate=True,
            early_exit=True,
            evaluation_runtime="all",
            conditions=(
                ConditionShape(rollout=30.0, has_properties=True, aggregation=1),
                ConditionShape(rollout=100.0, has_properties=True, aggregation=None),
                ConditionShape(rollout=0.0, has_properties=False, aggregation=1),
            ),
            variants=(60.0, 40.0),
        )
        sent = json.dumps(asdict(description))
        for value in (
            "email",
            "example.com",
            "4242",
            "control",
            "treatment",
            "Control arm",
            "fake-payload-token",
            "secret",
        ):
            assert value not in sent

    @parameterized.expand(
        [
            ("string_rollout_is_null", {"groups": [{"properties": [], "rollout_percentage": "50"}]}, {"rollout": None}),
            (
                "boolean_rollout_is_null",
                {"groups": [{"properties": [], "rollout_percentage": True}]},
                {"rollout": None},
            ),
            ("absent_rollout_reads_full", {"groups": [{"properties": []}]}, {"rollout": 100.0}),
            (
                "group_index_that_is_no_int_is_null",
                {"aggregation_group_type_index": "1", "groups": [{"properties": [], "rollout_percentage": 100}]},
                {"aggregation": None},
            ),
        ]
    )
    def test_condition_value_the_rule_cannot_read(self, _name: str, filters: dict[str, Any], condition: dict[str, Any]):
        expected = replace(FULL_PERSON_FLAG.conditions[0], **condition)
        assert describe_flag(_flag(filters)) == replace(FULL_PERSON_FLAG, conditions=(expected,))

    @parameterized.expand(
        [
            ("deleted", {"deleted": True}, {"active": False}),
            ("archived", {"archived": True}, {"active": False}),
            ("disabled", {"active": False}, {"active": False}),
            ("blank_runtime", {"evaluation_runtime": ""}, {"evaluation_runtime": None}),
            ("server_runtime", {"evaluation_runtime": "server"}, {"evaluation_runtime": "server"}),
        ]
    )
    def test_flag_state(self, _name: str, fields: dict[str, Any], expected: dict[str, Any]):
        filters = {"groups": [{"properties": [], "rollout_percentage": 100}]}
        assert describe_flag(_flag(filters, **fields)) == replace(FULL_PERSON_FLAG, **expected)

    def test_config_version_2_is_not_described(self):
        assert describe_flag(_flag({"version": 2, "groups": [{"properties": [], "rollout_percentage": 100}]})) is None
