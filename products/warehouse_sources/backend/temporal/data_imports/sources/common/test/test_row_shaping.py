import copy
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.row_shaping import (
    OnClash,
    camel_to_snake,
    flatten_jsonapi,
    flatten_nested,
    lift_nested,
)


class TestCamelToSnake(SimpleTestCase):
    @parameterized.expand(
        [
            ("pascal_case", "AnomalyStartDate", "anomaly_start_date"),
            ("camel_case", "totalImpact", "total_impact"),
            ("leading_acronym", "SOARecord", "soa_record"),
            ("trailing_acronym", "ResourceARN", "resource_arn"),
            ("digit_before_capital", "Ipv4Address", "ipv4_address"),
            ("already_snake", "snake_case", "snake_case"),
            ("single_word", "Name", "name"),
        ]
    )
    def test_converts(self, _name: str, value: str, expected: str) -> None:
        assert camel_to_snake(value) == expected


_RESOURCE: dict[str, Any] = {
    "id": "root-id",
    "type": "incidents",
    "attributes": {"id": "attr-id", "title": "Down", "owner_id": "attr-owner"},
    "relationships": {
        "owner": {"data": {"type": "users", "id": "u1"}},
        "service": {"data": {"type": "services", "id": "s1"}},
        "team": {"data": None},
        "tags": {"data": [{"type": "tags", "id": "t1"}]},
        "parent": {"links": {"related": "/parents/1"}},
    },
    "links": {"self": "/incidents/1"},
}


class TestFlattenJsonapi(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "root_wins_and_relationships_become_ids",
                True,
                "root",
                {
                    "id": "root-id",
                    "type": "incidents",
                    "links": {"self": "/incidents/1"},
                    "title": "Down",
                    "owner_id": "attr-owner",
                    "service_id": "s1",
                },
            ),
            (
                "nested_wins_and_relationships_become_ids",
                True,
                "nested",
                {
                    "id": "attr-id",
                    "type": "incidents",
                    "links": {"self": "/incidents/1"},
                    "title": "Down",
                    "owner_id": "u1",
                    "service_id": "s1",
                },
            ),
            (
                "root_wins_and_relationships_stay_raw",
                False,
                "root",
                {
                    "id": "root-id",
                    "type": "incidents",
                    "relationships": _RESOURCE["relationships"],
                    "links": {"self": "/incidents/1"},
                    "title": "Down",
                    "owner_id": "attr-owner",
                },
            ),
        ]
    )
    def test_flattens(
        self, _name: str, relationships_as_ids: bool, on_clash: OnClash, expected: dict[str, Any]
    ) -> None:
        item = copy.deepcopy(_RESOURCE)

        row = flatten_jsonapi(item, relationships_as_ids=relationships_as_ids, on_clash=on_clash)

        assert row == expected
        assert list(row) == list(expected)
        assert item == _RESOURCE

    @parameterized.expand(
        [
            ("missing", {"id": "1"}),
            ("null", {"id": "1", "attributes": None}),
            ("not_a_dict", {"id": "1", "attributes": ["x"]}),
        ]
    )
    def test_unusable_attributes_are_dropped(self, _name: str, item: dict[str, Any]) -> None:
        assert flatten_jsonapi(item) == {"id": "1"}


class TestLiftNested(SimpleTestCase):
    @parameterized.expand(
        [
            ("root_wins", "root", {"id": "root", "status": "ok", "name": "pipe"}),
            ("nested_wins", "nested", {"id": "nested", "status": "ok", "name": "pipe"}),
        ]
    )
    def test_lifts(self, _name: str, on_clash: OnClash, expected: dict[str, Any]) -> None:
        row = {"id": "root", "metadata": {"id": "nested", "name": "pipe"}, "status": "ok"}
        original = copy.deepcopy(row)

        flat = lift_nested(row, "metadata", on_clash=on_clash)

        assert flat == expected
        assert list(flat) == list(expected)
        assert row == original

    @parameterized.expand(
        [
            ("missing", {"id": 1}),
            ("null", {"id": 1, "metadata": None}),
            ("not_a_dict", {"id": 1, "metadata": "text"}),
        ]
    )
    def test_non_dict_value_leaves_row_unchanged(self, _name: str, row: dict[str, Any]) -> None:
        assert lift_nested(row, "metadata") == row


class TestFlattenNested(SimpleTestCase):
    _OBJ: dict[str, Any] = {
        "AnomalyId": "a1",
        "Impact": {"TotalImpact": 5, "Detail": {"MaxImpact": 2}},
        "Tags": {"Env": "prod"},
        "RootCauses": [{"LinkedAccount": "1"}, "plain"],
        "Wrapper": {"Tags": {"Team": "x"}},
    }

    @parameterized.expand(
        [
            (
                "recurses_into_dicts_and_leaves_lists",
                {},
                {
                    "anomaly_id": "a1",
                    "impact_total_impact": 5,
                    "impact_detail_max_impact": 2,
                    "tags_env": "prod",
                    "root_causes": [{"LinkedAccount": "1"}, "plain"],
                    "wrapper_tags_team": "x",
                },
            ),
            (
                "keep_raw_matches_original_key_at_every_depth",
                {"keep_raw": frozenset({"Tags"})},
                {
                    "anomaly_id": "a1",
                    "impact_total_impact": 5,
                    "impact_detail_max_impact": 2,
                    "tags": {"Env": "prod"},
                    "root_causes": [{"LinkedAccount": "1"}, "plain"],
                    "wrapper_tags": {"Team": "x"},
                },
            ),
            (
                "flatten_list_items_flattens_dicts_in_lists",
                {"flatten_list_items": True},
                {
                    "anomaly_id": "a1",
                    "impact_total_impact": 5,
                    "impact_detail_max_impact": 2,
                    "tags_env": "prod",
                    "root_causes": [{"linked_account": "1"}, "plain"],
                    "wrapper_tags_team": "x",
                },
            ),
            (
                "prefix_sep_and_key_fn",
                {"prefix": "total", "sep": ".", "key_fn": str.lower},
                {
                    "total.anomalyid": "a1",
                    "total.impact.totalimpact": 5,
                    "total.impact.detail.maximpact": 2,
                    "total.tags.env": "prod",
                    "total.rootcauses": [{"LinkedAccount": "1"}, "plain"],
                    "total.wrapper.tags.team": "x",
                },
            ),
        ]
    )
    def test_flattens(self, _name: str, kwargs: dict[str, Any], expected: dict[str, Any]) -> None:
        obj = copy.deepcopy(self._OBJ)

        assert flatten_nested(obj, **kwargs) == expected
        assert obj == self._OBJ
