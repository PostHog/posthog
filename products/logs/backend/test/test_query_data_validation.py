from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from products.logs.backend.presentation.views.api import LogsViewSet


class TestInvalidQueryDataResponse(SimpleTestCase):
    @parameterized.expand(
        [
            ("string", "SELECT * FROM logs"),
            ("list", ["a", "list"]),
            ("int", 42),
            ("bool", True),
            ("none", None),
        ]
    )
    def test_rejects_non_dict_query_data(self, _name, query_data):
        response = LogsViewSet._invalid_query_data_response(query_data)
        assert response is not None
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_accepts_dict_query_data(self):
        self.assertIsNone(LogsViewSet._invalid_query_data_response({"dateRange": {}}))


class TestQueryEndpointRejectsMalformedQuery(APIBaseTest):
    # A client sending `query` as a raw SQL-like string (rather than the expected object) used to
    # 500 with `AttributeError: 'str' object has no attribute 'get'` instead of a clean 400 —
    # every `.get()` call on `query_data` below the type check assumed it was always a dict.
    @parameterized.expand(
        [
            ("query", "logs/query"),
            ("export", "logs/export"),
        ]
    )
    def test_string_query_returns_400_not_500(self, _name, url_path):
        response = self.client.post(
            f"/api/projects/{self.team.id}/{url_path}",
            data={"query": "SELECT * FROM logs"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
