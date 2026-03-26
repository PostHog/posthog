import pytest
from posthog.test.base import APIBaseTest
from unittest import mock

from rest_framework import status

from products.endpoints.backend.api import EndpointViewSet
from products.endpoints.backend.tests.conftest import create_endpoint_with_version

pytestmark = [pytest.mark.django_db]


class TestShouldUseDuckLake(APIBaseTest):
    """Test the routing decision for DuckLake vs ClickHouse."""

    def _make_viewset(self) -> EndpointViewSet:
        viewset = EndpointViewSet()
        viewset.team_id = self.team.id
        return viewset

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
            sql="SELECT event, count(*) as cnt FROM events GROUP BY event",
            hogql="SELECT event, count() AS cnt FROM events GROUP BY event",
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
        assert data["backend"] == "ducklake"
        assert "ducklake_sql" not in data
        assert "hogql" not in data
        assert "query" not in data
        mock_execute.assert_called_once()

    @mock.patch("posthog.ducklake.client.execute_ducklake_query")
    @mock.patch("products.endpoints.backend.api.EndpointViewSet._should_use_ducklake", return_value=True)
    def test_run_with_debug_includes_sql_metadata(self, _mock_should, mock_execute):
        from posthog.ducklake.client import DuckLakeQueryResult

        mock_execute.return_value = DuckLakeQueryResult(
            columns=["cnt"],
            types=["20"],
            results=[[42]],
            sql="SELECT count(*) as cnt FROM events",
            hogql="SELECT count() AS cnt FROM events",
        )

        create_endpoint_with_version(
            name="dl-debug-test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT count() as cnt FROM events"},
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/dl-debug-test/run/",
            data={"debug": True},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["backend"] == "ducklake"
        assert data["query"] == "SELECT count() as cnt FROM events"
        assert "hogql" in data
        assert "ducklake_sql" in data

    @mock.patch("posthog.ducklake.client.execute_ducklake_query")
    @mock.patch("products.endpoints.backend.api.EndpointViewSet._should_use_ducklake", return_value=True)
    def test_run_ducklake_error_falls_back_to_inline(self, _mock_should, mock_execute):
        mock_execute.side_effect = Exception("Duckgres connection refused")

        create_endpoint_with_version(
            name="dl-error-test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT count() FROM events"},
            created_by=self.user,
        )

        with mock.patch("products.endpoints.backend.api.EndpointViewSet._execute_inline_endpoint") as mock_inline:
            from rest_framework.response import Response

            mock_inline.return_value = Response({"results": [], "columns": [], "hasMore": False}, status=200)
            response = self.client.get(f"/api/environments/{self.team.id}/endpoints/dl-error-test/run/")
            assert response.status_code == status.HTTP_200_OK
            mock_execute.assert_called_once()
            mock_inline.assert_called_once()
