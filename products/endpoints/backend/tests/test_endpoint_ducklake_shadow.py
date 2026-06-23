import pytest
from posthog.test.base import APIBaseTest
from unittest import mock

from rest_framework import status
from rest_framework.response import Response

from posthog.ducklake.client import DuckLakeQueryResult

from products.endpoints.backend.services import ducklake_shadow
from products.endpoints.backend.tests.conftest import create_endpoint_with_version

pytestmark = [pytest.mark.django_db]

HOGQL_QUERY = {"kind": "HogQLQuery", "query": "SELECT count() as cnt FROM events"}


class TestShadowDispatch(APIBaseTest):
    """The dispatch decision in EndpointExecutionService._maybe_shadow_ducklake."""

    def _inline_response(self) -> Response:
        return Response(
            {"results": [[1]], "columns": ["cnt"], "hasMore": False, "is_cached": False},
            status=status.HTTP_200_OK,
        )

    @mock.patch("products.endpoints.backend.services.execution.shadow_compare_ducklake_execution")
    @mock.patch(
        "products.endpoints.backend.services.execution.EndpointExecutionService._should_shadow_ducklake",
        return_value=True,
    )
    def test_dispatches_shadow_for_inline_execution(self, _mock_should, mock_task):
        endpoint = create_endpoint_with_version(
            name="shadow-inline", team=self.team, query=HOGQL_QUERY, created_by=self.user
        )
        version = endpoint.get_version()

        with mock.patch(
            "products.endpoints.backend.services.execution.EndpointExecutionService._execute_inline_endpoint",
            return_value=self._inline_response(),
        ):
            response = self.client.get(f"/api/environments/{self.team.id}/endpoints/shadow-inline/run/")

        assert response.status_code == status.HTTP_200_OK
        mock_task.delay.assert_called_once()
        kwargs = mock_task.delay.call_args.kwargs
        assert kwargs["team_id"] == self.team.pk
        assert kwargs["endpoint_id"] == str(endpoint.id)
        assert kwargs["version_id"] == str(version.id)
        assert kwargs["execution_type"] == "inline"
        assert kwargs["clickhouse_cached"] is False
        assert kwargs["clickhouse_row_count"] == 1
        assert isinstance(kwargs["clickhouse_ms"], float)

    @mock.patch("products.endpoints.backend.services.execution.shadow_compare_ducklake_execution")
    @mock.patch(
        "products.endpoints.backend.services.execution.EndpointExecutionService._should_shadow_ducklake",
        return_value=False,
    )
    def test_no_dispatch_when_flag_off(self, _mock_should, mock_task):
        create_endpoint_with_version(name="shadow-off", team=self.team, query=HOGQL_QUERY, created_by=self.user)

        with mock.patch(
            "products.endpoints.backend.services.execution.EndpointExecutionService._execute_inline_endpoint",
            return_value=self._inline_response(),
        ):
            response = self.client.get(f"/api/environments/{self.team.id}/endpoints/shadow-off/run/")

        assert response.status_code == status.HTTP_200_OK
        mock_task.delay.assert_not_called()


class TestShadowComparison(APIBaseTest):
    """The worker-side comparison in run_ducklake_shadow_comparison."""

    def _capture_events(self) -> list[dict]:
        captured: list[dict] = []
        cm = mock.MagicMock()
        cm.__enter__.return_value = lambda **kw: captured.append(kw)
        cm.__exit__.return_value = False
        self._cm_patch = mock.patch.object(ducklake_shadow, "ph_scoped_capture", return_value=cm)
        self._cm_patch.start()
        self.addCleanup(self._cm_patch.stop)
        server_patch = mock.patch.object(
            ducklake_shadow, "get_duckgres_server_for_organization", return_value=mock.MagicMock()
        )
        server_patch.start()
        self.addCleanup(server_patch.stop)
        return captured

    def test_emits_comparison_event_with_both_timings(self):
        endpoint = create_endpoint_with_version(name="cmp-ok", team=self.team, query=HOGQL_QUERY, created_by=self.user)
        version = endpoint.get_version()
        captured = self._capture_events()

        with mock.patch.object(
            ducklake_shadow,
            "execute_ducklake_query",
            return_value=DuckLakeQueryResult(
                columns=["cnt"], types=["20"], results=[[1]], sql="", hogql=None, connect_ms=8.0, query_ms=4.0
            ),
        ):
            ducklake_shadow.run_ducklake_shadow_comparison(
                team_id=self.team.pk,
                endpoint_id=str(endpoint.id),
                version_id=str(version.id),
                variables=None,
                execution_type="inline",
                clickhouse_cached=False,
                clickhouse_ms=12.5,
                clickhouse_row_count=1,
            )

        assert len(captured) == 1
        assert captured[0]["event"] == ducklake_shadow.SHADOW_EVENT
        props = captured[0]["properties"]
        assert props["clickhouse_ms"] == 12.5
        assert props["ducklake_ms"] is not None
        assert props["ducklake_connect_ms"] == 8.0
        assert props["ducklake_query_ms"] == 4.0
        assert props["clickhouse_row_count"] == 1
        assert props["ducklake_row_count"] == 1
        assert props["row_count_match"] is True
        assert props["ducklake_error"] is None
        assert props["execution_type"] == "inline"

    def test_emits_event_with_error_when_ducklake_fails(self):
        endpoint = create_endpoint_with_version(name="cmp-err", team=self.team, query=HOGQL_QUERY, created_by=self.user)
        version = endpoint.get_version()
        captured = self._capture_events()

        with mock.patch.object(
            ducklake_shadow, "execute_ducklake_query", side_effect=Exception("duckgres connection refused")
        ):
            ducklake_shadow.run_ducklake_shadow_comparison(
                team_id=self.team.pk,
                endpoint_id=str(endpoint.id),
                version_id=str(version.id),
                variables=None,
                execution_type="inline",
                clickhouse_cached=False,
                clickhouse_ms=12.5,
                clickhouse_row_count=1,
            )

        assert len(captured) == 1
        props = captured[0]["properties"]
        assert props["ducklake_ms"] is None
        assert props["ducklake_row_count"] is None
        assert props["row_count_match"] is None
        assert "duckgres connection refused" in props["ducklake_error"]

    def test_missing_entity_is_noop(self):
        captured = self._capture_events()

        ducklake_shadow.run_ducklake_shadow_comparison(
            team_id=self.team.pk,
            endpoint_id="00000000-0000-0000-0000-000000000000",
            version_id="00000000-0000-0000-0000-000000000000",
            variables=None,
            execution_type="inline",
            clickhouse_cached=False,
            clickhouse_ms=12.5,
            clickhouse_row_count=1,
        )

        assert captured == []

    def test_no_duckgres_server_is_noop(self):
        endpoint = create_endpoint_with_version(
            name="cmp-noserver", team=self.team, query=HOGQL_QUERY, created_by=self.user
        )
        version = endpoint.get_version()
        captured = self._capture_events()

        with mock.patch.object(ducklake_shadow, "get_duckgres_server_for_organization", return_value=None):
            ducklake_shadow.run_ducklake_shadow_comparison(
                team_id=self.team.pk,
                endpoint_id=str(endpoint.id),
                version_id=str(version.id),
                variables=None,
                execution_type="inline",
                clickhouse_cached=False,
                clickhouse_ms=12.5,
                clickhouse_row_count=1,
            )

        assert captured == []
