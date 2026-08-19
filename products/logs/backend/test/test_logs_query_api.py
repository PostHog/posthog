from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.errors import CHQueryErrorTableIsReadOnly, CHQueryErrorTooManyBytes
from posthog.exceptions import ClickHouseAtCapacity

_QUERY = {"dateRange": {"date_from": "-1h"}}

# A raw ClickHouse message that names infrastructure the client must never see.
_LEAKY_MESSAGE = "Table is in readonly mode: replica_path=/clickhouse/tables/logs/1/posthog.logs34/replicas/replica-3"


class TestLogsQueryApi(APIBaseTest):
    def _post_query_raising(self, raised: Exception):
        with patch(
            "products.logs.backend.presentation.views.api.time_sliced_results",
            side_effect=raised,
        ):
            return self.client.post(f"/api/projects/{self.team.id}/logs/query", data={"query": _QUERY})

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
        response = self._post_query_raising(raised)
        self.assertEqual(response.status_code, expected_status)
        self.assertIn("error", response.json())

    def test_transient_error_does_not_leak_internal_message(self):
        # CHQueryErrorTableIsReadOnly is transient but carries a raw message with the replica path,
        # so the 503 body must be a fixed message, not str(e).
        response = self._post_query_raising(
            CHQueryErrorTableIsReadOnly(_LEAKY_MESSAGE, code=242, code_name="table_is_read_only")
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertNotIn("replica_path", response.json()["error"])
