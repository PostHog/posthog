from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.errors import CHQueryErrorTooManyBytes
from posthog.exceptions import ClickHouseAtCapacity

_QUERY = {"dateRange": {"date_from": "-1h"}}


class TestLogsQueryApi(APIBaseTest):
    @parameterized.expand(
        [
            # A busy or briefly unavailable ClickHouse must read as retryable, not an application bug.
            ("capacity_is_retryable", ClickHouseAtCapacity(), status.HTTP_503_SERVICE_UNAVAILABLE),
            # A scan that reads too much data is the caller's to narrow, so it stays a clean 400.
            (
                "too_many_bytes_is_bad_request",
                CHQueryErrorTooManyBytes("read too much", code=241, code_name="too_many_bytes"),
                status.HTTP_400_BAD_REQUEST,
            ),
        ]
    )
    def test_query_maps_clickhouse_errors(self, _name, raised, expected_status):
        with patch(
            "products.logs.backend.presentation.views.api.time_sliced_results",
            side_effect=raised,
        ):
            response = self.client.post(f"/api/projects/{self.team.id}/logs/query", data={"query": _QUERY})

        self.assertEqual(response.status_code, expected_status)
        self.assertIn("error", response.json())
