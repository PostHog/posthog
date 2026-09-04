from django.test import SimpleTestCase

from parameterized import parameterized

from products.feature_flags.backend.persisted_flags import (
    get_dynamic_persisted_feature_flags,
    is_unconditionally_fully_rolled_out,
)


def _flag(filters: dict, active: bool = True, deleted: bool = False) -> dict:
    return {"key": "flag", "active": active, "deleted": deleted, "filters": filters}


class TestIsUnconditionallyFullyRolledOut(SimpleTestCase):
    @parameterized.expand(
        [
            ("explicit_100", _flag({"groups": [{"properties": [], "rollout_percentage": 100}]}), True),
            ("implicit_100", _flag({"groups": [{"properties": []}]}), True),
            ("empty_groups", _flag({"groups": []}), False),
            ("no_filters", _flag({}), False),
            ("partial_rollout", _flag({"groups": [{"properties": [], "rollout_percentage": 50}]}), False),
            (
                "has_properties",
                _flag({"groups": [{"properties": [{"key": "email"}], "rollout_percentage": 100}]}),
                False,
            ),
            (
                "multiple_blanket_groups",
                _flag(
                    {
                        "groups": [
                            {"properties": [], "rollout_percentage": 100},
                            {"properties": [], "rollout_percentage": 100},
                        ]
                    }
                ),
                True,
            ),
            (
                "targeted_group_plus_blanket_group",
                _flag(
                    {
                        "groups": [
                            {"properties": [{"key": "email"}], "rollout_percentage": 100},
                            {"properties": [], "rollout_percentage": 100},
                        ]
                    }
                ),
                True,
            ),
            (
                "targeted_group_plus_partial_blanket_group",
                _flag(
                    {
                        "groups": [
                            {"properties": [{"key": "email"}], "rollout_percentage": 100},
                            {"properties": [], "rollout_percentage": 50},
                        ]
                    }
                ),
                False,
            ),
            (
                "multivariate",
                _flag(
                    {
                        "groups": [{"properties": [], "rollout_percentage": 100}],
                        "multivariate": {"variants": [{"key": "a", "rollout_percentage": 100}]},
                    }
                ),
                False,
            ),
            (
                "holdout",
                _flag({"groups": [{"properties": [], "rollout_percentage": 100}], "holdout": {"id": "x"}}),
                False,
            ),
            (
                "super_groups",
                _flag(
                    {"groups": [{"properties": [], "rollout_percentage": 100}], "super_groups": [{"properties": []}]}
                ),
                False,
            ),
            (
                "group_aggregation",
                _flag({"groups": [{"properties": [], "rollout_percentage": 100}], "aggregation_group_type_index": 0}),
                False,
            ),
            (
                "variant_override",
                _flag({"groups": [{"properties": [], "rollout_percentage": 100, "variant": "test"}]}),
                False,
            ),
            ("inactive", _flag({"groups": [{"properties": [], "rollout_percentage": 100}]}, active=False), False),
            ("deleted", _flag({"groups": [{"properties": [], "rollout_percentage": 100}]}, deleted=True), False),
        ]
    )
    def test_predicate(self, _name: str, flag: dict, expected: bool) -> None:
        self.assertEqual(is_unconditionally_fully_rolled_out(flag), expected)


class TestGetDynamicPersistedFeatureFlags(SimpleTestCase):
    def test_merges_dynamic_with_static_deduped_and_sorted(self) -> None:
        definitions = [
            {
                "key": "rolled-out",
                "active": True,
                "deleted": False,
                "filters": {"groups": [{"rollout_percentage": 100}]},
            },
            {"key": "partial", "active": True, "deleted": False, "filters": {"groups": [{"rollout_percentage": 10}]}},
            {
                "key": "static-and-rolled-out",
                "active": True,
                "deleted": False,
                "filters": {"groups": [{"rollout_percentage": 100}]},
            },
        ]
        result = get_dynamic_persisted_feature_flags(definitions, ["static-only", "static-and-rolled-out"])
        self.assertEqual(result, ["rolled-out", "static-and-rolled-out", "static-only"])

    def test_none_definitions_returns_static_only(self) -> None:
        self.assertEqual(get_dynamic_persisted_feature_flags(None, ["a", "b"]), ["a", "b"])

    def test_no_static_keys(self) -> None:
        definitions = [
            {"key": "on", "active": True, "deleted": False, "filters": {"groups": [{"rollout_percentage": 100}]}}
        ]
        self.assertEqual(get_dynamic_persisted_feature_flags(definitions), ["on"])
