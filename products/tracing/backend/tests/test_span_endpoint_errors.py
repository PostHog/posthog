from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import ParseError

from posthog.errors import CHQueryErrorTooManyBytes

from products.tracing.backend.presentation.views import SpansViewSet, _serialize_compare_rows


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


class TestQueryBody(SimpleTestCase):
    @parameterized.expand(
        [
            ("array_body", ["x"]),
            ("string_body", "x"),
            ("array_query", {"query": ["x"]}),
            ("string_query", {"query": "x"}),
        ]
    )
    def test_rejects_non_object(self, _name, data):
        with self.assertRaises(ParseError):
            SpansViewSet._query_body(data)

    @parameterized.expand(
        [
            ("missing", {}, {}),
            ("null", {"query": None}, {}),
            ("object", {"query": {"serviceNames": ["web"]}}, {"serviceNames": ["web"]}),
        ]
    )
    def test_reads_the_query(self, _name, data, expected):
        self.assertEqual(SpansViewSet._query_body(data), expected)


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

    def test_count_rejects_a_non_object_query(self):
        # The body reaches the field reads unvalidated, so a non-object query used to raise an
        # AttributeError and surface as a 500.
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/count/",
            {"query": ["x"]},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_aggregate_rejects_malformed_compare_filter(self):
        # A compareFilter that fails validation must 400, not be swallowed into a 200 with
        # compare: null — otherwise a requested comparison silently disappears.
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/aggregate/",
            {"query": {"compareFilter": {"compare": True, "not_a_real_field": 1}}},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
