from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest import mock

from django.utils import timezone

from rest_framework import status
from rest_framework.response import Response

from posthog.schema import DataWarehouseSyncInterval, EventsNode, TrendsQuery

from posthog.models.insight_variable import InsightVariable

from products.data_warehouse.backend.models import DataWarehouseTable
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.endpoints.backend.api import EndpointViewSet
from products.endpoints.backend.tests.conftest import create_endpoint_with_version


class TestEndpointExecution(ClickhouseTestMixin, APIBaseTest):
    """
    Tests for the endpoint execution API.

    Design principles:
    1. `variables` is the preferred mechanism for passing dynamic values
    2. API behavior is consistent regardless of query type (HogQL vs Insight)
    3. API behavior is consistent regardless of materialization status
    4. `date_from` and `date_to` are magic variables for insight endpoints
    5. `query_override` is not allowed
    6. `filters_override` is deprecated but supported for insight endpoints (not HogQL)
    7. Unknown variables cause errors
    """

    def setUp(self):
        super().setUp()

        # Create test events
        for event_name in ["$pageview", "$pageleave"]:
            for day in range(1, 11):
                _create_event(
                    event=event_name,
                    distinct_id="user1",
                    team=self.team,
                    timestamp=f"2026-01-{day:02d} 12:00:00",
                    properties={"$browser": "Chrome" if day % 2 == 0 else "Safari", "$os": "Mac"},
                )

        flush_persons_and_events()

        # Create variables for reuse
        self.event_name_var = InsightVariable.objects.create(
            team=self.team,
            name="Event Name",
            code_name="event_name",
            type=InsightVariable.Type.STRING,
            default_value="$pageview",
        )

        # Mock sync_saved_query_workflow to avoid Temporal connection
        self.sync_workflow_patcher = mock.patch(
            "products.data_warehouse.backend.data_load.saved_query_service.sync_saved_query_workflow"
        )
        self.sync_workflow_patcher.start()

    def tearDown(self):
        self.sync_workflow_patcher.stop()
        super().tearDown()

    def _materialize_endpoint(self, endpoint, table_name: str | None = None):
        """Helper to enable materialization and set up a completed materialized table."""
        flush_persons_and_events()

        # Enable materialization via API
        response = self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"is_materialized": True, "sync_frequency": DataWarehouseSyncInterval.FIELD_24HOUR},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()

        # Set up materialized table as completed
        version = endpoint.versions.first()
        version.refresh_from_db()
        saved_query = version.saved_query
        assert saved_query is not None

        saved_query.status = DataWarehouseSavedQuery.Status.COMPLETED
        saved_query.last_run_at = timezone.now()
        saved_query.table = DataWarehouseTable.objects.create(
            team=self.team,
            name=table_name or endpoint.name,
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern=f"s3://test-bucket/{table_name or endpoint.name}",
        )
        saved_query.save()

        return saved_query

    # =========================================================================
    # NON-MATERIALIZED HOGQL ENDPOINTS
    # =========================================================================

    def test_hogql_endpoint_executes_with_default_variable(self):
        endpoint = create_endpoint_with_version(
            name="hogql_with_default",
            team=self.team,
            query={
                "kind": "HogQLQuery",
                "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
                "variables": {
                    str(self.event_name_var.id): {
                        "variableId": str(self.event_name_var.id),
                        "code_name": "event_name",
                        "value": "$pageview",
                    }
                },
            },
            created_by=self.user,
            is_active=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/", {}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should count only $pageview events (10 events)
        self.assertEqual(response.json()["results"][0][0], 10)

    def test_hogql_endpoint_executes_with_variable_override(self):
        endpoint = create_endpoint_with_version(
            name="hogql_var_override",
            team=self.team,
            query={
                "kind": "HogQLQuery",
                "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
                "variables": {
                    str(self.event_name_var.id): {
                        "variableId": str(self.event_name_var.id),
                        "code_name": "event_name",
                        "value": "$pageview",
                    }
                },
            },
            created_by=self.user,
            is_active=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"variables": {"event_name": "$pageleave"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should count only $pageleave events (10 events)
        self.assertEqual(response.json()["results"][0][0], 10)

    def test_hogql_endpoint_rejects_unknown_variable(self):
        endpoint = create_endpoint_with_version(
            name="hogql_unknown_var",
            team=self.team,
            query={
                "kind": "HogQLQuery",
                "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
                "variables": {
                    str(self.event_name_var.id): {
                        "variableId": str(self.event_name_var.id),
                        "code_name": "event_name",
                        "value": "$pageview",
                    }
                },
            },
            created_by=self.user,
            is_active=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"variables": {"nonexistent_var": "value"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("nonexistent_var", response.json()["detail"])

    def test_hogql_endpoint_rejects_query_override(self):
        endpoint = create_endpoint_with_version(
            name="hogql_no_override",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            is_active=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"query_override": {"query": "SELECT 2"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("query_override", response.json()["detail"])

    def test_hogql_endpoint_rejects_filters_override(self):
        endpoint = create_endpoint_with_version(
            name="hogql_no_filters",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            is_active=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"filters_override": {"date_from": "2026-01-01"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("filters_override is not allowed for HogQL endpoints", response.json()["detail"])

    # =========================================================================
    # NON-MATERIALIZED INSIGHT ENDPOINTS
    # =========================================================================

    def test_insight_endpoint_executes_with_defaults(self):
        endpoint = create_endpoint_with_version(
            name="trends_default",
            team=self.team,
            query=TrendsQuery(series=[EventsNode(event="$pageview")]).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/", {}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.json())

    def test_insight_endpoint_accepts_date_from_variable(self):
        endpoint = create_endpoint_with_version(
            name="trends_date_from",
            team=self.team,
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                dateRange={
                    "date_from": "2026-01-01",
                    "date_to": "2026-01-10",
                },  # Explicit range covering all test events
            ).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        # First, get results without date filter to establish baseline (all 10 events)
        response_no_filter = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"refresh": "force"},
            format="json",
        )
        self.assertEqual(response_no_filter.status_code, status.HTTP_200_OK)
        baseline_data = sum(response_no_filter.json()["results"][0]["data"])

        # Now with date_from filter - should have fewer results (days 5-10 only, not 1-10)
        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"variables": {"date_from": "2026-01-05", "date_to": "2026-01-10"}, "debug": True, "refresh": "force"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        # Verify date range was applied in debug output
        self.assertIn("2026-01-05", response_data.get("resolved_date_range", {}).get("date_from", ""))

        # Verify actual filtering occurred - filtered results should be less than baseline
        filtered_data = sum(response_data["results"][0]["data"])
        self.assertLess(filtered_data, baseline_data, "date_from filter should reduce result count")

    def test_insight_endpoint_accepts_date_to_variable(self):
        endpoint = create_endpoint_with_version(
            name="trends_date_to",
            team=self.team,
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                dateRange={"date_from": "2026-01-01"},  # Fixed start
            ).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        # With date_to filter - should limit to days 1-5 only
        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"variables": {"date_from": "2026-01-01", "date_to": "2026-01-05"}, "debug": True, "refresh": "force"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        # Verify date range was applied in debug output
        self.assertIn("2026-01-05", response_data.get("resolved_date_range", {}).get("date_to", ""))

        # Verify results exist - events for days 1-5 should be present
        filtered_data = sum(response_data["results"][0]["data"])
        self.assertGreater(filtered_data, 0, "Should have results for dates 1-5")

    def test_insight_endpoint_rejects_unknown_variable(self):
        endpoint = create_endpoint_with_version(
            name="trends_unknown_var",
            team=self.team,
            query=TrendsQuery(series=[EventsNode(event="$pageview")]).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"variables": {"unknown_var": "value"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("unknown_var", response.json()["detail"])

    def test_insight_endpoint_rejects_query_override(self):
        endpoint = create_endpoint_with_version(
            name="trends_no_override",
            team=self.team,
            query=TrendsQuery(series=[EventsNode(event="$pageview")]).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"query_override": {"interval": "hour"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("query_override", response.json()["detail"])

    def test_insight_endpoint_accepts_filters_override_for_backwards_compat(self):
        endpoint = create_endpoint_with_version(
            name="trends_filters_override",
            team=self.team,
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                dateRange={
                    "date_from": "2026-01-01",
                    "date_to": "2026-01-10",
                },  # Explicit range covering all test events
            ).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        # Get baseline without date filter (all 10 events)
        response_baseline = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"refresh": "force"},
            format="json",
        )
        self.assertEqual(response_baseline.status_code, status.HTTP_200_OK)
        baseline_total = sum(response_baseline.json()["results"][0]["data"])

        # Use filters_override to filter by date - should have fewer results (days 5-10)
        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"filters_override": {"date_from": "2026-01-05", "date_to": "2026-01-10"}, "refresh": "force"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        filtered_total = sum(response.json()["results"][0]["data"])
        self.assertLess(filtered_total, baseline_total)

    def test_insight_endpoint_filters_override_returns_deprecation_header(self):
        endpoint = create_endpoint_with_version(
            name="trends_deprecation_header",
            team=self.team,
            query=TrendsQuery(series=[EventsNode(event="$pageview")]).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"filters_override": {"date_from": "2026-01-01"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("X-PostHog-Warn", response.headers)
        self.assertIn("filters_override is deprecated", response.headers["X-PostHog-Warn"])

    def test_insight_endpoint_filters_override_takes_precedence_over_variables(self):
        endpoint = create_endpoint_with_version(
            name="trends_precedence",
            team=self.team,
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                dateRange={"date_from": "-30d"},
            ).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        # filters_override uses date_from 2026-01-08 (days 8-10), variables uses 2026-01-02 (days 2-10)
        # If filters_override wins, we should have fewer results
        response_filters = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {
                "filters_override": {"date_from": "2026-01-08"},
                "variables": {"date_from": "2026-01-02"},
                "refresh": "force",
            },
            format="json",
        )
        self.assertEqual(response_filters.status_code, status.HTTP_200_OK)
        filters_total = sum(response_filters.json()["results"][0]["data"])

        # Use only variables with same date to verify
        response_vars = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"variables": {"date_from": "2026-01-08"}, "refresh": "force"},
            format="json",
        )
        self.assertEqual(response_vars.status_code, status.HTTP_200_OK)
        vars_total = sum(response_vars.json()["results"][0]["data"])

        # Both should have same result since filters_override wins with same date
        self.assertEqual(filters_total, vars_total)

    # =========================================================================
    # MATERIALIZED HOGQL ENDPOINTS
    # =========================================================================

    def test_materialized_hogql_endpoint_filters_by_variable(self):
        endpoint = create_endpoint_with_version(
            name="mat_hogql_var",
            team=self.team,
            query={
                "kind": "HogQLQuery",
                "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
                "variables": {
                    str(self.event_name_var.id): {
                        "variableId": str(self.event_name_var.id),
                        "code_name": "event_name",
                        "value": "$pageview",
                    }
                },
            },
            created_by=self.user,
            is_active=True,
        )
        self._materialize_endpoint(endpoint)

        # Execute with variable filter - should filter materialized table by event_name
        with mock.patch.object(EndpointViewSet, "_execute_query_and_respond", return_value=Response({})) as mock_exec:
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
                {"variables": {"event_name": "$pageleave"}},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            mock_exec.assert_called()
            # Verify the query has WHERE clause filtering by event_name
            query_request_data = mock_exec.call_args[0][0]
            query_sql = query_request_data["query"]["query"].lower()
            self.assertIn("event_name", query_sql)
            self.assertIn("$pageleave", query_sql)

    def test_materialized_hogql_endpoint_selects_only_original_columns(self):
        endpoint = create_endpoint_with_version(
            name="mat_hogql_cols",
            team=self.team,
            query={
                "kind": "HogQLQuery",
                "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
                "variables": {
                    str(self.event_name_var.id): {
                        "variableId": str(self.event_name_var.id),
                        "code_name": "event_name",
                        "value": "$pageview",
                    }
                },
            },
            created_by=self.user,
            is_active=True,
        )
        self._materialize_endpoint(endpoint)

        with mock.patch.object(EndpointViewSet, "_execute_query_and_respond", return_value=Response({})) as mock_exec:
            self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
                {"variables": {"event_name": "$pageview"}},
                format="json",
            )

            mock_exec.assert_called()
            query_sql = mock_exec.call_args[0][0]["query"]["query"]
            # Should select the original column (count()), not * or event_name
            select_part = query_sql.split("FROM")[0]
            self.assertNotIn("*", select_part)
            self.assertNotIn("event_name", select_part.lower())

    def test_materialized_hogql_endpoint_rejects_unknown_variable(self):
        endpoint = create_endpoint_with_version(
            name="mat_hogql_unknown",
            team=self.team,
            query={
                "kind": "HogQLQuery",
                "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
                "variables": {
                    str(self.event_name_var.id): {
                        "variableId": str(self.event_name_var.id),
                        "code_name": "event_name",
                        "value": "$pageview",
                    }
                },
            },
            created_by=self.user,
            is_active=True,
        )
        self._materialize_endpoint(endpoint)

        # Try to filter by a variable that wasn't materialized
        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"variables": {"not_materialized": "value"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not_materialized", response.json()["detail"])

    def test_materialized_hogql_endpoint_requires_variable(self):
        endpoint = create_endpoint_with_version(
            name="mat_hogql_required_var",
            team=self.team,
            query={
                "kind": "HogQLQuery",
                "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
                "variables": {
                    str(self.event_name_var.id): {
                        "variableId": str(self.event_name_var.id),
                        "code_name": "event_name",
                        "value": "$pageview",
                    }
                },
            },
            created_by=self.user,
            is_active=True,
        )
        self._materialize_endpoint(endpoint)

        # Omitting the variable should fail - not return all data
        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {},  # No variables provided
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("event_name", response.json()["detail"])
        self.assertIn("required", response.json()["detail"].lower())

    def test_materialized_endpoint_requires_all_variables(self):
        var2 = InsightVariable.objects.create(
            team=self.team,
            name="Browser",
            code_name="browser",
            type=InsightVariable.Type.STRING,
            default_value="Chrome",
        )

        endpoint = create_endpoint_with_version(
            name="mat_hogql_partial_var",
            team=self.team,
            query={
                "kind": "HogQLQuery",
                "query": "SELECT count() FROM events WHERE event = {variables.event_name} AND properties.$browser = {variables.browser}",
                "variables": {
                    str(self.event_name_var.id): {
                        "variableId": str(self.event_name_var.id),
                        "code_name": "event_name",
                        "value": "$pageview",
                    },
                    str(var2.id): {
                        "variableId": str(var2.id),
                        "code_name": "browser",
                        "value": "Chrome",
                    },
                },
            },
            created_by=self.user,
            is_active=True,
        )
        self._materialize_endpoint(endpoint)

        # Provide only one variable — should fail listing the missing one
        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"variables": {"event_name": "$pageview"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("browser", response.json()["detail"])
        self.assertIn("required", response.json()["detail"].lower())

    def test_materialized_endpoint_requires_all_variables_none_provided(self):
        var2 = InsightVariable.objects.create(
            team=self.team,
            name="Browser2",
            code_name="browser2",
            type=InsightVariable.Type.STRING,
            default_value="Chrome",
        )

        endpoint = create_endpoint_with_version(
            name="mat_hogql_no_vars",
            team=self.team,
            query={
                "kind": "HogQLQuery",
                "query": "SELECT count() FROM events WHERE event = {variables.event_name} AND properties.$browser = {variables.browser2}",
                "variables": {
                    str(self.event_name_var.id): {
                        "variableId": str(self.event_name_var.id),
                        "code_name": "event_name",
                        "value": "$pageview",
                    },
                    str(var2.id): {
                        "variableId": str(var2.id),
                        "code_name": "browser2",
                        "value": "Chrome",
                    },
                },
            },
            created_by=self.user,
            is_active=True,
        )
        self._materialize_endpoint(endpoint)

        # No variables at all — should fail listing all required
        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        detail = response.json()["detail"]
        self.assertIn("event_name", detail)
        self.assertIn("browser2", detail)
        self.assertIn("required", detail.lower())

    def test_materialized_hogql_endpoint_direct_refresh_bypasses_materialization(self):
        endpoint = create_endpoint_with_version(
            name="mat_hogql_direct",
            team=self.team,
            query={
                "kind": "HogQLQuery",
                "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
                "variables": {
                    str(self.event_name_var.id): {
                        "variableId": str(self.event_name_var.id),
                        "code_name": "event_name",
                        "value": "$pageview",
                    }
                },
            },
            created_by=self.user,
            is_active=True,
        )
        self._materialize_endpoint(endpoint)

        # refresh: direct should bypass materialization and run inline
        with (
            mock.patch.object(
                EndpointViewSet, "_execute_materialized_endpoint", return_value=Response({})
            ) as mock_materialized,
            mock.patch.object(EndpointViewSet, "_execute_inline_endpoint", return_value=Response({})) as mock_inline,
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
                {"variables": {"event_name": "$pageview"}, "refresh": "direct"},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            mock_inline.assert_called_once()
            mock_materialized.assert_not_called()

    def test_materialized_hogql_endpoint_filters_by_multiple_variables(self):
        var2 = InsightVariable.objects.create(
            team=self.team,
            name="Browser",
            code_name="browser",
            type=InsightVariable.Type.STRING,
            default_value="Chrome",
        )

        endpoint = create_endpoint_with_version(
            name="mat_hogql_multi",
            team=self.team,
            query={
                "kind": "HogQLQuery",
                "query": "SELECT count() FROM events WHERE event = {variables.event_name} AND properties.$browser = {variables.browser}",
                "variables": {
                    str(self.event_name_var.id): {
                        "variableId": str(self.event_name_var.id),
                        "code_name": "event_name",
                        "value": "$pageview",
                    },
                    str(var2.id): {
                        "variableId": str(var2.id),
                        "code_name": "browser",
                        "value": "Chrome",
                    },
                },
            },
            created_by=self.user,
            is_active=True,
        )
        self._materialize_endpoint(endpoint)

        with mock.patch.object(EndpointViewSet, "_execute_query_and_respond", return_value=Response({})) as mock_exec:
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
                {"variables": {"event_name": "$pageleave", "browser": "Safari"}},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            mock_exec.assert_called()
            query_sql = mock_exec.call_args[0][0]["query"]["query"].lower()
            self.assertIn("event_name", query_sql)
            self.assertIn("$pageleave", query_sql)
            self.assertIn("browser", query_sql)
            self.assertIn("safari", query_sql)

    def test_materialized_hogql_endpoint_filters_by_range_variables(self):
        start_var = InsightVariable.objects.create(
            team=self.team,
            name="Start Date",
            code_name="start_date",
            type=InsightVariable.Type.STRING,
            default_value="2026-01-01",
        )
        end_var = InsightVariable.objects.create(
            team=self.team,
            name="End Date",
            code_name="end_date",
            type=InsightVariable.Type.STRING,
            default_value="2026-01-10",
        )

        endpoint = create_endpoint_with_version(
            name="mat_hogql_range",
            team=self.team,
            query={
                "kind": "HogQLQuery",
                "query": "SELECT count() FROM events WHERE timestamp >= {variables.start_date} AND timestamp < {variables.end_date}",
                "variables": {
                    str(start_var.id): {
                        "variableId": str(start_var.id),
                        "code_name": "start_date",
                        "value": "2026-01-01",
                    },
                    str(end_var.id): {
                        "variableId": str(end_var.id),
                        "code_name": "end_date",
                        "value": "2026-01-10",
                    },
                },
            },
            created_by=self.user,
            is_active=True,
        )
        self._materialize_endpoint(endpoint)

        with mock.patch.object(EndpointViewSet, "_execute_query_and_respond", return_value=Response({})) as mock_exec:
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
                {"variables": {"start_date": "2026-01-05", "end_date": "2026-01-08"}},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            mock_exec.assert_called()
            query_sql = mock_exec.call_args[0][0]["query"]["query"].lower()
            self.assertIn("start_date", query_sql)
            self.assertIn("end_date", query_sql)
            # HogQL prints >= as greaterorequals() and < as less()
            self.assertIn("greaterorequals", query_sql)
            self.assertIn("less(", query_sql)

    # =========================================================================
    # MATERIALIZED INSIGHT ENDPOINTS
    # =========================================================================

    def test_materialized_insight_endpoint_filters_by_breakdown(self):
        endpoint = create_endpoint_with_version(
            name="mat_trends_breakdown",
            team=self.team,
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                breakdownFilter={"breakdowns": [{"property": "$browser", "type": "event"}]},
            ).model_dump(),
            created_by=self.user,
            is_active=True,
        )
        self._materialize_endpoint(endpoint)

        # Filter by breakdown using actual property name
        with mock.patch.object(EndpointViewSet, "_execute_query_and_respond", return_value=Response({})) as mock_exec:
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
                {"variables": {"$browser": "Chrome"}},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            mock_exec.assert_called()
            query_request_data = mock_exec.call_args[0][0]
            query_sql = query_request_data["query"]["query"].lower()
            # Must use has() for array containment, not = for string equality
            self.assertIn("has(breakdown_value", query_sql)
            self.assertIn("chrome", query_sql)

    def test_materialized_insight_endpoint_rejects_date_variables(self):
        endpoint = create_endpoint_with_version(
            name="mat_trends_dates",
            team=self.team,
            query=TrendsQuery(series=[EventsNode(event="$pageview")]).model_dump(),
            created_by=self.user,
            is_active=True,
        )
        self._materialize_endpoint(endpoint)

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"variables": {"date_from": "2026-01-05", "date_to": "2026-01-08"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("date_from", response.json()["detail"])

    def test_materialized_insight_endpoint_rejects_unknown_breakdown(self):
        endpoint = create_endpoint_with_version(
            name="mat_trends_unknown_bd",
            team=self.team,
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                breakdownFilter={"breakdowns": [{"property": "$browser", "type": "event"}]},
            ).model_dump(),
            created_by=self.user,
            is_active=True,
        )
        self._materialize_endpoint(endpoint)

        # Try to filter by a property that wasn't in the breakdown
        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"variables": {"$os": "Mac"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("$os", response.json()["detail"])

    def test_materialized_insight_endpoint_requires_breakdown_variable(self):
        endpoint = create_endpoint_with_version(
            name="mat_trends_required_breakdown",
            team=self.team,
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                breakdownFilter={"breakdowns": [{"property": "$browser", "type": "event"}]},
            ).model_dump(),
            created_by=self.user,
            is_active=True,
        )
        self._materialize_endpoint(endpoint)

        # Omitting the breakdown variable should fail - not return all breakdown values
        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {},  # No variables provided
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("$browser", response.json()["detail"])
        self.assertIn("required", response.json()["detail"].lower())

    def test_materialized_insight_endpoint_accepts_filters_override_instead_of_variable(self):
        endpoint = create_endpoint_with_version(
            name="mat_trends_filters_fallback",
            team=self.team,
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                breakdownFilter={"breakdowns": [{"property": "$browser", "type": "event"}]},
            ).model_dump(),
            created_by=self.user,
            is_active=True,
        )
        self._materialize_endpoint(endpoint)

        # Using filters_override instead of variables should work (backwards compat)
        with mock.patch.object(EndpointViewSet, "_execute_query_and_respond", return_value=Response({})) as mock_exec:
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
                {"filters_override": {"properties": [{"key": "$browser", "value": "Chrome", "type": "event"}]}},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            mock_exec.assert_called()

    def test_materialized_insight_endpoint_direct_refresh_bypasses_materialization(self):
        endpoint = create_endpoint_with_version(
            name="mat_trends_direct",
            team=self.team,
            query=TrendsQuery(series=[EventsNode(event="$pageview")]).model_dump(),
            created_by=self.user,
            is_active=True,
        )
        self._materialize_endpoint(endpoint)

        with (
            mock.patch.object(
                EndpointViewSet, "_execute_materialized_endpoint", return_value=Response({})
            ) as mock_materialized,
            mock.patch.object(EndpointViewSet, "_execute_inline_endpoint", return_value=Response({})) as mock_inline,
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
                {"refresh": "direct"},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            mock_inline.assert_called_once()
            mock_materialized.assert_not_called()

    # =========================================================================
    # MATERIALIZATION CONSTRAINTS
    # =========================================================================

    def test_endpoint_with_multiple_variables_can_be_materialized(self):
        var2 = InsightVariable.objects.create(
            team=self.team,
            name="Browser",
            code_name="browser",
            type=InsightVariable.Type.STRING,
            default_value="Chrome",
        )

        endpoint = create_endpoint_with_version(
            name="multi_var_endpoint",
            team=self.team,
            query={
                "kind": "HogQLQuery",
                "query": "SELECT count() FROM events WHERE event = {variables.event_name} AND properties.$browser = {variables.browser}",
                "variables": {
                    str(self.event_name_var.id): {
                        "variableId": str(self.event_name_var.id),
                        "code_name": "event_name",
                        "value": "$pageview",
                    },
                    str(var2.id): {
                        "variableId": str(var2.id),
                        "code_name": "browser",
                        "value": "Chrome",
                    },
                },
            },
            created_by=self.user,
            is_active=True,
        )

        self.assertIsNotNone(endpoint.id)

        # Enabling materialization should succeed for multiple equality variables
        response = self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"is_materialized": True, "sync_frequency": DataWarehouseSyncInterval.FIELD_24HOUR},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["is_materialized"])

    def test_endpoint_with_multiple_breakdowns_cannot_be_materialized(self):
        endpoint = create_endpoint_with_version(
            name="multi_breakdown",
            team=self.team,
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                breakdownFilter={
                    "breakdowns": [
                        {"property": "$browser", "type": "event"},
                        {"property": "$os", "type": "event"},
                    ]
                },
            ).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        # Endpoint creation should succeed
        self.assertIsNotNone(endpoint.id)

        # But enabling materialization should fail
        response = self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"is_materialized": True, "sync_frequency": DataWarehouseSyncInterval.FIELD_24HOUR},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("multiple breakdowns", response.json()["detail"].lower())

    # =========================================================================
    # ENDPOINT EXECUTION WITHOUT VARIABLES (SIMPLE CASES)
    # =========================================================================

    def test_hogql_endpoint_without_variables_executes(self):
        endpoint = create_endpoint_with_version(
            name="simple_hogql",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 42 as answer"},
            created_by=self.user,
            is_active=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/", {}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"][0][0], 42)

    def test_insight_endpoint_without_breakdown_executes(self):
        endpoint = create_endpoint_with_version(
            name="simple_trends",
            team=self.team,
            query=TrendsQuery(series=[EventsNode(event="$pageview")]).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/", {}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.json())

    # =========================================================================
    # NON-MATERIALIZED INSIGHT ENDPOINTS WITH BREAKDOWN
    # =========================================================================

    def test_non_materialized_insight_endpoint_accepts_breakdown_variable(self):
        from posthog.schema import Breakdown, BreakdownFilter, BreakdownType

        endpoint = create_endpoint_with_version(
            name="trends_breakdown_filter",
            team=self.team,
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser", type=BreakdownType.EVENT)]),
            ).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        # Breakdown variable should be accepted (not rejected as unknown)
        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"variables": {"$browser": "Chrome"}, "debug": True},
            format="json",
        )

        # Should succeed, not fail with "Unknown variable" error
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        # Verify properties filter was applied
        result = response_data["results"][0] if response_data.get("results") else {}
        if "filter" in result:
            filter_props = result["filter"].get("properties", [])
            self.assertTrue(
                any(p.get("key") == "$browser" and p.get("value") == "Chrome" for p in filter_props),
                "Breakdown property filter should be applied",
            )

    def test_non_materialized_insight_endpoint_accepts_breakdown_and_date_variables(self):
        from posthog.schema import Breakdown, BreakdownFilter, BreakdownType

        endpoint = create_endpoint_with_version(
            name="trends_breakdown_dates",
            team=self.team,
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser", type=BreakdownType.EVENT)]),
                dateRange={"date_from": "-30d"},
            ).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        # Filter by both breakdown and date - should be accepted (not rejected)
        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {
                "variables": {
                    "$browser": "Chrome",
                    "date_from": "2026-01-05",
                    "date_to": "2026-01-08",
                },
                "debug": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        # Verify date range was applied
        self.assertIn("2026-01-05", response_data.get("resolved_date_range", {}).get("date_from", ""))
        self.assertIn("2026-01-08", response_data.get("resolved_date_range", {}).get("date_to", ""))

        # Verify properties filter was applied
        result = response_data["results"][0] if response_data.get("results") else {}
        if "filter" in result:
            filter_props = result["filter"].get("properties", [])
            self.assertTrue(
                any(p.get("key") == "$browser" and p.get("value") == "Chrome" for p in filter_props),
                "Breakdown property filter should be applied",
            )
