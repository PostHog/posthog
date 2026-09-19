import json

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.errors import CHQueryErrorTooManyBytes

from products.tracing.backend.presentation.views import _serialize_compare_rows


class _FakeRow:
    def __init__(self, value: int) -> None:
        self.value = value

    def model_dump(self) -> dict:
        return {"value": self.value}


class TestSerializeCompareRows(SimpleTestCase):
    @parameterized.expand(
        [
            # None means "no comparison requested" and must stay null; an empty list means
            # "comparison ran, window matched nothing" and must survive as [] — collapsing it
            # to null (the shipped bug) hides that the comparison happened.
            ("not_requested", None, None),
            ("requested_empty_window", [], []),
        ]
    )
    def test_preserves_none_vs_empty(self, _name, compare_rows, expected):
        self.assertEqual(_serialize_compare_rows(compare_rows), expected)

    def test_serializes_rows(self):
        self.assertEqual(_serialize_compare_rows([_FakeRow(1), _FakeRow(2)]), [{"value": 1}, {"value": 2}])


class TestSpanCountErrorHandling(APIBaseTest):
    def test_count_over_byte_cap_returns_400_not_500(self):
        # The count is a bounded pre-flight; exceeding ClickHouse's byte cap must surface as an
        # actionable 400 rather than the opaque 500 the raw CHQueryErrorTooManyBytes would produce.
        with patch(
            "products.tracing.backend.presentation.views.run_count_query",
            side_effect=CHQueryErrorTooManyBytes("too many bytes"),
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/tracing/spans/count/",
                {"query": {"dateRange": {"date_from": "-30d"}}},
                format="json",
            )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("narrow", response.json()["detail"].lower())

    def test_aggregate_rejects_malformed_compare_filter(self):
        # A compareFilter that fails validation must 400, not be swallowed into a 200 with
        # compare: null — otherwise a requested comparison silently disappears.
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/aggregate/",
            {"query": {"compareFilter": {"compare": True, "not_a_real_field": 1}}},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)


class TestSpanFilterKeyValidation(APIBaseTest):
    @parameterized.expand(
        [
            # The two filter-extraction paths: the per-span runner mixin, and the aggregation mixin.
            ("query", "query"),
            ("aggregate", "aggregate"),
        ]
    )
    def test_unknown_span_filter_key_returns_400_not_500(self, _name, endpoint):
        # An OTel attribute key sent as type "span" used to reach the HogQL resolver as an unknown
        # field, so a caller mistake surfaced as a server error.
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/{endpoint}/",
            {
                "query": {
                    "dateRange": {"date_from": "-1h"},
                    "filterGroup": [{"key": "sessionId", "type": "span", "operator": "exact", "value": ["abc"]}],
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("span_attribute", json.dumps(response.json()))

    def test_unknown_span_filter_key_returns_400_on_generic_query_endpoint(self):
        # The same runner serves the generic query endpoint, which answers 400 for a HogQL query
        # error but 500 for any other exception out of the runner constructor.
        response = self.client.post(
            f"/api/environments/{self.team.id}/query/",
            {
                "query": {
                    "kind": "TraceSpansQuery",
                    "dateRange": {"date_from": "-1h"},
                    "filterGroup": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [{"key": "sessionId", "type": "span", "operator": "exact", "value": ["abc"]}],
                            }
                        ],
                    },
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("span_attribute", json.dumps(response.json()))
