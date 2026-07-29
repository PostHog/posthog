from unittest import TestCase

from parameterized import parameterized

from posthog.schema import PropertyGroupFilter

from products.logs.backend.presentation.filter_group_validation import normalize_filter_group

_LEAF = {"type": "log_entry", "key": "message", "operator": "icontains", "value": "health"}
_INNER_GROUP = {"type": "AND", "values": [_LEAF]}


class TestNormalizeFilterGroup(TestCase):
    @parameterized.expand(
        [
            ("none", None, {"type": "AND", "values": []}),
            ("empty_list", [], {"type": "AND", "values": []}),
            ("bare_leaf_list", [_LEAF], {"type": "AND", "values": [_INNER_GROUP]}),
            # Off-by-one dict: leaf sits directly under the top-level group. This is the shape
            # behind the query-endpoint 500s and the alert-check crash loop.
            ("flat_dict_with_leaf", {"type": "AND", "values": [_LEAF]}, {"type": "AND", "values": [_INNER_GROUP]}),
            # Canonical shapes pass through untouched.
            ("empty_group", {"type": "AND", "values": []}, {"type": "AND", "values": []}),
            ("canonical_nested", {"type": "AND", "values": [_INNER_GROUP]}, {"type": "AND", "values": [_INNER_GROUP]}),
        ]
    )
    def test_normalizes_to_expected_shape(self, _name: str, value: object, expected: dict) -> None:
        assert normalize_filter_group(value) == expected

    @parameterized.expand(
        [
            ("bare_leaf_list", [_LEAF]),
            ("flat_dict_with_leaf", {"type": "AND", "values": [_LEAF]}),
            (
                "flat_dict_resource_attribute_leaf",
                {
                    "type": "AND",
                    "values": [
                        {
                            "type": "log_resource_attribute",
                            "key": "deployment.environment",
                            "operator": "exact",
                            "value": "production",
                        }
                    ],
                },
            ),
            ("canonical_nested", {"type": "AND", "values": [_INNER_GROUP]}),
        ]
    )
    def test_output_validates_as_property_group_filter(self, _name: str, value: object) -> None:
        # The whole point of normalization: these loose shapes must survive
        # PropertyGroupFilter validation instead of raising (which 500s the query
        # endpoint / crashes the alert check on every run).
        PropertyGroupFilter.model_validate(normalize_filter_group(value))
