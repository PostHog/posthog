import pytest
from posthog.test.base import APIBaseTest
from unittest import mock

from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from posthog.ducklake.client import DuckLakeQueryResult

from products.endpoints.backend.services import ducklake_shadow
from products.endpoints.backend.services.execution import EndpointExecutionService
from products.endpoints.backend.tests.conftest import create_endpoint_with_version

pytestmark = [pytest.mark.django_db]

HOGQL_QUERY = {"kind": "HogQLQuery", "query": "SELECT count() as cnt FROM events"}
TRENDS_QUERY = {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]}


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
        assert kwargs["limit"] is None
        assert kwargs["offset"] is None

    @mock.patch("products.endpoints.backend.services.execution.shadow_compare_ducklake_execution")
    @mock.patch(
        "products.endpoints.backend.services.execution.EndpointExecutionService._should_shadow_ducklake",
        return_value=True,
    )
    def test_no_dispatch_on_cache_hit(self, _mock_should, mock_task):
        create_endpoint_with_version(name="shadow-cached", team=self.team, query=HOGQL_QUERY, created_by=self.user)
        cached = Response(
            {"results": [[1]], "columns": ["cnt"], "hasMore": False, "is_cached": True},
            status=status.HTTP_200_OK,
        )

        with mock.patch(
            "products.endpoints.backend.services.execution.EndpointExecutionService._execute_inline_endpoint",
            return_value=cached,
        ):
            response = self.client.get(f"/api/environments/{self.team.id}/endpoints/shadow-cached/run/")

        assert response.status_code == status.HTTP_200_OK
        mock_task.delay.assert_not_called()

    @mock.patch("products.endpoints.backend.services.execution.shadow_compare_ducklake_execution")
    @mock.patch(
        "products.endpoints.backend.services.execution.EndpointExecutionService._should_shadow_ducklake",
        return_value=True,
    )
    def test_dispatch_propagates_pagination(self, _mock_should, mock_task):
        create_endpoint_with_version(name="shadow-paged", team=self.team, query=HOGQL_QUERY, created_by=self.user)

        with mock.patch(
            "products.endpoints.backend.services.execution.EndpointExecutionService._execute_inline_endpoint",
            return_value=self._inline_response(),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/shadow-paged/run/",
                data={"limit": 5, "offset": 2},
                content_type="application/json",
            )

        assert response.status_code == status.HTTP_200_OK
        kwargs = mock_task.delay.call_args.kwargs
        assert kwargs["limit"] == 5
        assert kwargs["offset"] == 2

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
        ) as mock_execute:
            ducklake_shadow.run_ducklake_shadow_comparison(
                team_id=self.team.pk,
                endpoint_id=str(endpoint.id),
                version_id=str(version.id),
                variables=None,
                execution_type="inline",
                clickhouse_cached=False,
                clickhouse_ms=12.5,
                clickhouse_row_count=1,
                limit=None,
                offset=None,
            )

        assert mock_execute.call_args.kwargs["bypass_warehouse_access_control"] is True
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
                limit=None,
                offset=None,
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
            limit=None,
            offset=None,
        )

        assert captured == []

    def test_no_duckgres_server_is_noop_in_prod(self):
        endpoint = create_endpoint_with_version(
            name="cmp-noserver", team=self.team, query=HOGQL_QUERY, created_by=self.user
        )
        version = endpoint.get_version()
        captured = self._capture_events()

        with (
            mock.patch.object(ducklake_shadow, "is_dev_mode", return_value=False),
            mock.patch.object(ducklake_shadow, "get_duckgres_server_for_organization", return_value=None),
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
                limit=None,
                offset=None,
            )

        assert captured == []

    def test_dev_mode_shadows_without_provisioned_server(self):
        endpoint = create_endpoint_with_version(name="cmp-dev", team=self.team, query=HOGQL_QUERY, created_by=self.user)
        version = endpoint.get_version()
        captured = self._capture_events()

        with (
            mock.patch.object(ducklake_shadow, "is_dev_mode", return_value=True),
            mock.patch.object(ducklake_shadow, "get_duckgres_server_for_organization", return_value=None),
            mock.patch.object(
                ducklake_shadow,
                "execute_ducklake_query",
                return_value=DuckLakeQueryResult(columns=["cnt"], types=["20"], results=[[1]], sql="", hogql=None),
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
                limit=None,
                offset=None,
            )

        assert len(captured) == 1


class TestShouldShadowDucklake(APIBaseTest):
    """The real gating in EndpointExecutionService._should_shadow_ducklake (unmocked)."""

    def _service(self) -> EndpointExecutionService:
        request = APIRequestFactory().get("/")
        return EndpointExecutionService(team=self.team, request=request)

    def test_does_not_shadow_during_test_suite(self):
        # is_dev_mode() is True under the test suite (USE_LOCAL_SETUP = TEST or ...), but the shadow
        # must not fire during tests: it builds a userless HogQL database and runs eagerly under Celery,
        # which trips access-control assertions on unrelated runs (e.g. PSAK system-table gating).
        endpoint = create_endpoint_with_version(
            name="should-shadow-test", team=self.team, query=HOGQL_QUERY, created_by=self.user
        )
        assert self._service()._should_shadow_ducklake(endpoint, endpoint.get_version()) is False

    @mock.patch("products.endpoints.backend.services.execution.is_dev_mode", return_value=True)
    def test_shadows_in_local_dev(self, _mock_dev):
        endpoint = create_endpoint_with_version(
            name="should-shadow-dev", team=self.team, query=HOGQL_QUERY, created_by=self.user
        )
        with self.settings(TEST=False):
            assert self._service()._should_shadow_ducklake(endpoint, endpoint.get_version()) is True

    @mock.patch("products.endpoints.backend.services.execution.is_dev_mode", return_value=True)
    def test_no_shadow_for_non_hogql_query(self, _mock_dev):
        endpoint = create_endpoint_with_version(
            name="should-shadow-trends", team=self.team, query=TRENDS_QUERY, created_by=self.user
        )
        with self.settings(TEST=False):
            assert self._service()._should_shadow_ducklake(endpoint, endpoint.get_version()) is False

    @mock.patch("products.endpoints.backend.services.execution.is_dev_mode", return_value=False)
    @mock.patch("products.endpoints.backend.services.execution.posthoganalytics.feature_enabled")
    def test_shadows_in_prod_when_flag_enabled(self, mock_flag, _mock_dev):
        endpoint = create_endpoint_with_version(
            name="should-shadow-flag", team=self.team, query=HOGQL_QUERY, created_by=self.user
        )
        version = endpoint.get_version()
        with self.settings(TEST=False):
            mock_flag.return_value = True
            assert self._service()._should_shadow_ducklake(endpoint, version) is True
            mock_flag.return_value = False
            assert self._service()._should_shadow_ducklake(endpoint, version) is False
