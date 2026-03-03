import pytest
from posthog.test.base import APIBaseTest
from unittest import mock

from parameterized import parameterized
from rest_framework import status

from products.endpoints.backend.api import EndpointViewSet
from products.endpoints.backend.tests.conftest import create_endpoint_with_version

pytestmark = [pytest.mark.django_db]


class TestHogQLToDuckLakeSQL(APIBaseTest):
    """Test HogQL -> Postgres SQL compilation for DuckLake queries."""

    def _compile(self, hogql: str) -> str:
        viewset = EndpointViewSet()
        viewset.team_id = self.team.id
        return viewset._hogql_to_ducklake_sql({"kind": "HogQLQuery", "query": hogql})

    @parameterized.expand(
        [
            (
                "basic_select",
                "SELECT event FROM events LIMIT 10",
                "events",
            ),
            (
                "where_clause",
                "SELECT event FROM events WHERE event = '$pageview'",
                "WHERE",
            ),
            (
                "group_by",
                "SELECT event, count() FROM events GROUP BY event",
                "GROUP BY",
            ),
            (
                "order_by",
                "SELECT event, count() as c FROM events GROUP BY event ORDER BY c DESC",
                "ORDER BY",
            ),
            (
                "count_aggregation",
                "SELECT count() FROM events",
                "count",
            ),
        ]
    )
    def test_sql_generation(self, _name: str, hogql: str, expected_fragment: str):
        sql = self._compile(hogql)
        assert expected_fragment.lower() in sql.lower(), f"Expected '{expected_fragment}' in SQL: {sql}"

    def test_produces_valid_postgres_dialect(self):
        sql = self._compile("SELECT event, count() FROM events GROUP BY event ORDER BY count() DESC LIMIT 5")
        assert "FORMAT" not in sql
        assert "SETTINGS" not in sql


class TestShouldUseDuckLake(APIBaseTest):
    """Test the routing decision for DuckLake vs ClickHouse."""

    def _make_viewset(self) -> EndpointViewSet:
        viewset = EndpointViewSet()
        viewset.team_id = self.team.id
        return viewset

    def test_hogql_query_with_duckgres_server_returns_true(self):
        endpoint = create_endpoint_with_version(
            name="dl-test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT count() FROM events"},
            created_by=self.user,
        )
        version = endpoint.get_version()
        viewset = self._make_viewset()

        with mock.patch("posthog.ducklake.common.is_dev_mode", return_value=False):
            with mock.patch(
                "posthog.ducklake.common.get_duckgres_server_for_team",
                return_value=mock.MagicMock(),
            ):
                assert viewset._should_use_ducklake(endpoint, version) is True

    def test_hogql_query_without_duckgres_server_returns_false(self):
        endpoint = create_endpoint_with_version(
            name="dl-test-no-server",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT count() FROM events"},
            created_by=self.user,
        )
        version = endpoint.get_version()
        viewset = self._make_viewset()

        with mock.patch("posthog.ducklake.common.is_dev_mode", return_value=False):
            with mock.patch(
                "posthog.ducklake.common.get_duckgres_server_for_team",
                return_value=None,
            ):
                assert viewset._should_use_ducklake(endpoint, version) is False

    def test_non_hogql_query_returns_false(self):
        endpoint = create_endpoint_with_version(
            name="dl-test-insight",
            team=self.team,
            query={"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
            created_by=self.user,
        )
        version = endpoint.get_version()
        viewset = self._make_viewset()

        assert viewset._should_use_ducklake(endpoint, version) is False

    def test_none_version_returns_false(self):
        endpoint = create_endpoint_with_version(
            name="dl-test-none",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT count() FROM events"},
            created_by=self.user,
        )
        viewset = self._make_viewset()

        assert viewset._should_use_ducklake(endpoint, None) is False

    def test_dev_mode_returns_true_for_hogql(self):
        endpoint = create_endpoint_with_version(
            name="dl-test-dev",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT count() FROM events"},
            created_by=self.user,
        )
        version = endpoint.get_version()
        viewset = self._make_viewset()

        with mock.patch("posthog.ducklake.common.is_dev_mode", return_value=True):
            with mock.patch.dict("os.environ", {"DUCKLAKE_ENDPOINTS_ENABLED": "true"}):
                assert viewset._should_use_ducklake(endpoint, version) is True

    def test_dev_mode_without_env_var_returns_false(self):
        endpoint = create_endpoint_with_version(
            name="dl-test-dev-off",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT count() FROM events"},
            created_by=self.user,
        )
        version = endpoint.get_version()
        viewset = self._make_viewset()

        with mock.patch("posthog.ducklake.common.is_dev_mode", return_value=True):
            with mock.patch.dict("os.environ", {}, clear=False):
                import os

                os.environ.pop("DUCKLAKE_ENDPOINTS_ENABLED", None)
                assert viewset._should_use_ducklake(endpoint, version) is False


class TestDuckLakeEndpointExecution(APIBaseTest):
    """Integration tests for the full DuckLake execution path via the run() API."""

    def setUp(self):
        super().setUp()
        self.sync_workflow_patcher = mock.patch(
            "products.data_warehouse.backend.data_load.saved_query_service.sync_saved_query_workflow"
        )
        self.sync_workflow_patcher.start()

    def tearDown(self):
        self.sync_workflow_patcher.stop()
        super().tearDown()

    @mock.patch("posthog.ducklake.client.execute_ducklake_query")
    @mock.patch("products.endpoints.backend.api.EndpointViewSet._should_use_ducklake", return_value=True)
    def test_run_returns_ducklake_result(self, _mock_should, mock_execute):
        from posthog.ducklake.client import DuckLakeQueryResult

        mock_execute.return_value = DuckLakeQueryResult(
            columns=["event", "cnt"],
            types=["25", "20"],
            results=[["$pageview", 42], ["$pageleave", 7]],
        )

        create_endpoint_with_version(
            name="dl-run-test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT event, count() as cnt FROM events GROUP BY event"},
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/dl-run-test/run/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["columns"] == ["event", "cnt"]
        assert data["results"] == [["$pageview", 42], ["$pageleave", 7]]
        assert data["hasMore"] is False
        mock_execute.assert_called_once()

    @mock.patch("posthog.ducklake.client.execute_ducklake_query")
    @mock.patch("products.endpoints.backend.api.EndpointViewSet._should_use_ducklake", return_value=True)
    def test_run_ducklake_error_raises(self, _mock_should, mock_execute):
        mock_execute.side_effect = Exception("Duckgres connection refused")

        create_endpoint_with_version(
            name="dl-error-test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT count() FROM events"},
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/dl-error-test/run/")
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    @mock.patch("products.endpoints.backend.api.EndpointViewSet._should_use_ducklake", return_value=False)
    def test_run_falls_back_to_clickhouse_when_ducklake_unavailable(self, _mock_should):
        create_endpoint_with_version(
            name="dl-fallback-test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT count() FROM events"},
            created_by=self.user,
        )

        with mock.patch("products.endpoints.backend.api.EndpointViewSet._execute_inline_endpoint") as mock_inline:
            from rest_framework.response import Response

            mock_inline.return_value = Response({"results": []}, status=200)
            self.client.get(f"/api/environments/{self.team.id}/endpoints/dl-fallback-test/run/")
            mock_inline.assert_called_once()
