from posthog.test.base import APIBaseTest
from unittest.mock import patch

from clickhouse_driver.errors import NetworkError, SocketTimeoutError
from parameterized import parameterized
from rest_framework import status

from posthog.hogql.errors import QueryError

from posthog.errors import ExposedCHQueryError

SPARKLINE_RUNNER = "products.logs.backend.presentation.views.api.SparklineQueryRunner.run"
LOGS_RUNNER = "products.logs.backend.presentation.views.api.LogsQueryRunner.run"


class TestLogsViewerQueryErrors(APIBaseTest):
    def _post(self, endpoint, runner_path, error):
        with patch(runner_path, side_effect=error):
            return self.client.post(
                f"/api/projects/{self.team.pk}/logs/{endpoint}",
                data={
                    "query": {
                        "dateRange": {"date_from": "-1h", "date_to": None},
                        "liveLogsCheckpoint": "2025-12-16T00:00:00Z",
                    }
                },
            )

    @parameterized.expand(
        [
            ("sparkline", SPARKLINE_RUNNER),
            ("query", LOGS_RUNNER),
        ]
    )
    def test_user_query_error_returns_400_with_message(self, endpoint, runner_path):
        for error in (QueryError("bad log query"), ExposedCHQueryError("bad clickhouse query", code=43)):
            with self.subTest(error=type(error).__name__):
                response = self._post(endpoint, runner_path, error)

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.json()["error"], str(error))

    @parameterized.expand(
        [
            ("sparkline", SPARKLINE_RUNNER),
            ("query", LOGS_RUNNER),
        ]
    )
    def test_unreachable_logs_workload_returns_503_with_message(self, endpoint, runner_path):
        # The logs cluster refusing a connection used to escape as a bare 500, so the viewer could
        # only show DRF's "A server error occurred." with nothing to act on.
        for error in (NetworkError("connect timeout"), SocketTimeoutError("socket timeout")):
            with self.subTest(error=type(error).__name__):
                response = self._post(endpoint, runner_path, error)

                self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
                self.assertIn("try again", response.json()["detail"].lower())
