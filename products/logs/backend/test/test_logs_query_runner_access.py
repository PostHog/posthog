from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.schema import DateRange, FilterLogicalOperator, LogsQuery, PropertyGroupFilter

from posthog.rbac.user_access_control import UserAccessControlError

from products.logs.backend.logs_query_runner import LogsQueryRunner


def _minimal_query_data() -> dict:
    return {
        "dateRange": {"date_from": "2024-01-01T00:00:00Z", "date_to": "2024-01-02T00:00:00Z"},
        "filterGroup": {"type": "AND", "values": []},
        "severityLevels": [],
        "serviceNames": [],
    }


def _build_runner(team) -> LogsQueryRunner:
    return LogsQueryRunner(
        team=team,
        query=LogsQuery(
            dateRange=DateRange(date_from="2024-01-01T00:00:00Z", date_to="2024-01-02T00:00:00Z"),
            filterGroup=PropertyGroupFilter(type=FilterLogicalOperator.AND_, values=[]),
            severityLevels=[],
            serviceNames=[],
            kind="LogsQuery",
        ),
    )


class TestLogsQueryRunnerAccess(APIBaseTest):
    def test_validate_query_runner_access_always_blocks_with_user(self):
        runner = _build_runner(self.team)

        with self.assertRaises(UserAccessControlError):
            runner.validate_query_runner_access(self.user)

    def test_run_without_user_skips_access_check(self):
        """Celery export tasks call run() without a user — access check must be skipped."""
        runner = _build_runner(self.team)

        with patch.object(runner, "_calculate") as mock_calculate:
            from posthog.schema import LogsQueryResponse

            mock_calculate.return_value = LogsQueryResponse(results=[], hasMore=False)
            response = runner.run()
            assert response is not None

    def test_run_with_user_raises_access_error(self):
        """User-initiated queries via the generic endpoint must be blocked."""
        runner = _build_runner(self.team)

        with self.assertRaises(UserAccessControlError):
            runner.run(user=self.user)


class TestLogsQueryBlockedOnGenericEndpoint(APIBaseTest):
    def test_generic_query_endpoint_rejects_logs_query(self):
        response = self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            data={
                "query": {
                    "kind": "LogsQuery",
                    **_minimal_query_data(),
                },
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Access control failure" in response.json()["detail"]
