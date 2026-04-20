"""Tests proving materialized insight endpoints must produce the same response shape as non-materialized ones.

These tests are written TDD-style: they define the expected contract and initially FAIL because the
materialized path currently returns flat HogQL data instead of rich insight-specific responses.
"""

from datetime import date

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest import mock

from django.utils import timezone

from rest_framework import status

from posthog.schema import (
    Breakdown,
    BreakdownFilter,
    BreakdownType,
    DataWarehouseSyncInterval,
    EventsNode,
    HogQLQueryResponse,
    LifecycleQuery,
    RetentionFilter,
    RetentionQuery,
    TrendsQuery,
)

from products.data_warehouse.backend.models import DataWarehouseTable
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.endpoints.backend.tests.conftest import create_endpoint_with_version

pytestmark = [pytest.mark.django_db]

# Fields that every TrendsQuery result dict must have
TRENDS_REQUIRED_FIELDS = {"data", "labels", "days", "count", "label", "action"}
# Fields that every LifecycleQuery result dict must have
LIFECYCLE_REQUIRED_FIELDS = {"data", "labels", "days", "count", "label", "action", "status"}
# Fields that every RetentionQuery result dict must have
RETENTION_REQUIRED_FIELDS = {"values", "label", "date"}


class TestInsightResponseParity(ClickhouseTestMixin, APIBaseTest):
    """Materialized insight endpoints must return the same response shape as non-materialized ones."""

    def setUp(self):
        super().setUp()

        for day in range(1, 11):
            _create_event(
                event="$pageview",
                distinct_id="user1",
                team=self.team,
                timestamp=f"2026-01-{day:02d} 12:00:00",
                properties={"$browser": "Chrome" if day % 2 == 0 else "Safari"},
            )

        flush_persons_and_events()

        self.sync_workflow_patcher = mock.patch(
            "products.data_warehouse.backend.data_load.saved_query_service.sync_saved_query_workflow"
        )
        self.workflow_exists_patcher = mock.patch(
            "products.data_warehouse.backend.data_load.saved_query_service.saved_query_workflow_exists",
            return_value=False,
        )
        self.sync_workflow_patcher.start()
        self.workflow_exists_patcher.start()

    def tearDown(self):
        self.sync_workflow_patcher.stop()
        self.workflow_exists_patcher.stop()
        super().tearDown()

    def _materialize_endpoint(self, endpoint):
        """Enable materialization and set up a completed saved query with table."""
        response = self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"is_materialized": True, "sync_frequency": DataWarehouseSyncInterval.FIELD_24HOUR},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()

        version = endpoint.versions.first()
        version.refresh_from_db()
        saved_query = version.saved_query
        assert saved_query is not None

        saved_query.status = DataWarehouseSavedQuery.Status.COMPLETED
        saved_query.last_run_at = timezone.now()
        saved_query.table = DataWarehouseTable.objects.create(
            team=self.team,
            name=f"{endpoint.name}_v1",
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern=f"s3://test-bucket/{endpoint.name}_v1",
        )
        saved_query.save()

        return saved_query

    def _run_endpoint(self, endpoint, **kwargs):
        return self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"refresh": "force", **kwargs},
            format="json",
        )

    # =========================================================================
    # TRENDS
    # =========================================================================

    def test_materialized_trends_has_insight_shape(self):
        endpoint = create_endpoint_with_version(
            name="trends_parity",
            team=self.team,
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                dateRange={"date_from": "2026-01-01", "date_to": "2026-01-10"},
            ).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        # Step 1: Execute inline — establish the baseline shape
        inline_resp = self._run_endpoint(endpoint)
        assert inline_resp.status_code == status.HTTP_200_OK
        inline_results = inline_resp.json()["results"]
        assert len(inline_results) > 0
        assert isinstance(inline_results[0], dict)
        for field in TRENDS_REQUIRED_FIELDS:
            assert field in inline_results[0], f"Inline response missing '{field}'"

        # Step 2: Set up materialization
        self._materialize_endpoint(endpoint)

        # Step 3: Mock process_query_model to return flat HogQL data
        # (simulating what the materialized table would produce)
        dates = [date(2026, 1, d) for d in range(1, 11)]
        totals = [1.0] * 10
        flat_response = HogQLQueryResponse(
            results=[(dates, totals)],
            columns=["date", "total"],
            types=["Array(Date)", "Array(Float64)"],
            hasMore=False,
        )

        with mock.patch(
            "products.endpoints.backend.api.process_query_model",
            return_value=flat_response,
        ):
            mat_resp = self._run_endpoint(endpoint)

        assert mat_resp.status_code == status.HTTP_200_OK
        mat_results = mat_resp.json()["results"]
        assert len(mat_results) > 0

        # The materialized response must have the same insight shape
        first = mat_results[0]
        assert isinstance(first, dict), f"Expected dict, got {type(first).__name__}: {first}"
        for field in TRENDS_REQUIRED_FIELDS:
            assert field in first, f"Materialized response missing '{field}'"

        # Value assertions: the mock data has 10 days with count 1.0 each
        assert first["data"] == [1.0] * 10, f"Unexpected data values: {first['data']}"
        assert first["count"] == 10.0, f"Unexpected count: {first['count']}"
        assert len(first["labels"]) == 10, f"Expected 10 labels, got {len(first['labels'])}"
        assert len(first["days"]) == 10, f"Expected 10 days, got {len(first['days'])}"

    def test_materialized_trends_with_breakdown_has_insight_shape(self):
        endpoint = create_endpoint_with_version(
            name="trends_bd_parity",
            team=self.team,
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser", type=BreakdownType.EVENT)]),
                dateRange={"date_from": "2026-01-01", "date_to": "2026-01-10"},
            ).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        # Step 1: Inline baseline
        inline_resp = self._run_endpoint(endpoint)
        assert inline_resp.status_code == status.HTTP_200_OK
        inline_results = inline_resp.json()["results"]
        assert len(inline_results) > 0
        assert "breakdown_value" in inline_results[0]

        # Step 2: Materialize
        self._materialize_endpoint(endpoint)

        # Step 3: Mock with breakdown_value column
        dates = [date(2026, 1, d) for d in range(1, 11)]
        flat_response = HogQLQueryResponse(
            results=[
                (dates, [1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0], ["Chrome"]),
                (dates, [0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0], ["Safari"]),
            ],
            columns=["date", "total", "breakdown_value"],
            types=["Array(Date)", "Array(Float64)", "Array(String)"],
            hasMore=False,
        )

        with mock.patch(
            "products.endpoints.backend.api.process_query_model",
            return_value=flat_response,
        ):
            mat_resp = self._run_endpoint(endpoint, variables={"$browser": "Chrome"})

        assert mat_resp.status_code == status.HTTP_200_OK, mat_resp.json()
        mat_results = mat_resp.json()["results"]
        assert len(mat_results) > 0

        first = mat_results[0]
        assert isinstance(first, dict), f"Expected dict, got {type(first).__name__}: {first}"
        for field in TRENDS_REQUIRED_FIELDS:
            assert field in first, f"Materialized breakdown response missing '{field}'"
        assert "breakdown_value" in first, "Materialized breakdown response missing 'breakdown_value'"

        # Value assertions: verify breakdown values are present and data has correct length
        breakdown_values = [str(r["breakdown_value"]) for r in mat_results]
        assert any("Chrome" in bv for bv in breakdown_values), (
            f"Expected Chrome in breakdown values: {breakdown_values}"
        )
        assert len(first["data"]) == 10, f"Expected 10 data points, got {len(first['data'])}"

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def test_materialized_lifecycle_has_insight_shape(self):
        endpoint = create_endpoint_with_version(
            name="lifecycle_parity",
            team=self.team,
            query=LifecycleQuery(
                series=[EventsNode(event="$pageview")],
                dateRange={"date_from": "2026-01-01", "date_to": "2026-01-10"},
            ).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        # Step 1: Inline baseline
        inline_resp = self._run_endpoint(endpoint)
        assert inline_resp.status_code == status.HTTP_200_OK
        inline_results = inline_resp.json()["results"]
        assert len(inline_results) > 0
        assert isinstance(inline_results[0], dict)
        for field in LIFECYCLE_REQUIRED_FIELDS:
            assert field in inline_results[0], f"Inline lifecycle response missing '{field}'"

        # Step 2: Materialize
        self._materialize_endpoint(endpoint)

        # Step 3: Mock with lifecycle columns in ALPHABETICAL order
        # (matching real materialized table behavior — Delta/Parquet sorts columns)
        dates = [date(2026, 1, d) for d in range(1, 11)]
        flat_response = HogQLQueryResponse(
            results=[
                (dates, "new", [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
                (dates, "returning", [0, 1, 1, 1, 1, 1, 1, 1, 1, 1]),
                (dates, "resurrecting", [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
                (dates, "dormant", [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            ],
            columns=["date", "status", "total"],
            types=["Array(Date)", "String", "Array(Int64)"],
            hasMore=False,
        )

        with mock.patch(
            "products.endpoints.backend.api.process_query_model",
            return_value=flat_response,
        ):
            mat_resp = self._run_endpoint(endpoint)

        assert mat_resp.status_code == status.HTTP_200_OK
        mat_results = mat_resp.json()["results"]
        assert len(mat_results) > 0

        first = mat_results[0]
        assert isinstance(first, dict), f"Expected dict, got {type(first).__name__}: {first}"
        for field in LIFECYCLE_REQUIRED_FIELDS:
            assert field in first, f"Materialized lifecycle response missing '{field}'"

        # Value assertions: verify lifecycle statuses are present
        statuses = {r["status"] for r in mat_results}
        assert statuses == {"new", "returning", "resurrecting", "dormant"}, f"Unexpected statuses: {statuses}"
        # Each status should have 10 data points
        for r in mat_results:
            assert len(r["data"]) == 10, f"Status {r['status']}: expected 10 data points, got {len(r['data'])}"

    # =========================================================================
    # RETENTION
    # =========================================================================

    def test_materialized_retention_has_insight_shape(self):
        endpoint = create_endpoint_with_version(
            name="retention_parity",
            team=self.team,
            query=RetentionQuery(
                retentionFilter=RetentionFilter(),
                dateRange={"date_from": "2026-01-01", "date_to": "2026-01-10"},
            ).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        # Step 1: Inline baseline
        inline_resp = self._run_endpoint(endpoint)
        assert inline_resp.status_code == status.HTTP_200_OK
        inline_results = inline_resp.json()["results"]
        assert len(inline_results) > 0
        assert isinstance(inline_results[0], dict)
        for field in RETENTION_REQUIRED_FIELDS:
            assert field in inline_results[0], f"Inline retention response missing '{field}'"
        # Retention results have nested "values" with "count" and "label"
        assert isinstance(inline_results[0]["values"], list)
        assert "count" in inline_results[0]["values"][0]
        assert "label" in inline_results[0]["values"][0]

        # Step 2: Materialize
        self._materialize_endpoint(endpoint)

        # Step 3: Mock with retention columns in ALPHABETICAL order
        # (matching real materialized table behavior — Delta/Parquet sorts columns)
        flat_response = HogQLQueryResponse(
            results=[
                (1, 0, 0),
                (1, 1, 0),
                (1, 0, 1),
                (1, 1, 1),
                (0, 0, 2),
                (0, 1, 2),
            ],
            columns=["count", "intervals_from_base", "start_event_matching_interval"],
            types=["UInt64", "Int64", "Int64"],
            hasMore=False,
        )

        with mock.patch(
            "products.endpoints.backend.api.process_query_model",
            return_value=flat_response,
        ):
            mat_resp = self._run_endpoint(endpoint)

        assert mat_resp.status_code == status.HTTP_200_OK
        mat_results = mat_resp.json()["results"]
        assert len(mat_results) > 0

        first = mat_results[0]
        assert isinstance(first, dict), f"Expected dict, got {type(first).__name__}: {first}"
        for field in RETENTION_REQUIRED_FIELDS:
            assert field in first, f"Materialized retention response missing '{field}'"
        assert isinstance(first["values"], list), "Retention values should be a list"
        assert "count" in first["values"][0], "Retention values missing 'count'"
        assert "label" in first["values"][0], "Retention values missing 'label'"

        # Value assertions: first cohort (interval 0) should have count=1 at base
        assert first["values"][0]["count"] == 1, f"Expected count=1 at base, got {first['values'][0]['count']}"
        # Retention creates one cohort per date interval in the range (10 days = 10 cohorts)
        assert len(mat_results) >= 3, f"Expected at least 3 cohorts, got {len(mat_results)}"

    # =========================================================================
    # MULTI-SERIES TRENDS
    # =========================================================================

    def test_materialized_multi_series_trends_has_insight_shape(self):
        endpoint = create_endpoint_with_version(
            name="multi_trends_parity",
            team=self.team,
            query=TrendsQuery(
                series=[
                    EventsNode(event="$pageview"),
                    EventsNode(event="$pageview", math="dau"),
                ],
                dateRange={"date_from": "2026-01-01", "date_to": "2026-01-10"},
            ).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        # Step 1: Inline baseline — should have results from both series
        inline_resp = self._run_endpoint(endpoint)
        assert inline_resp.status_code == status.HTTP_200_OK
        inline_results = inline_resp.json()["results"]
        assert len(inline_results) >= 2, f"Expected 2+ series, got {len(inline_results)}"

        # Step 2: Materialize
        self._materialize_endpoint(endpoint)

        # Step 3: Mock with __series_index column in ALPHABETICAL order
        # (matching real materialized table behavior — Delta/Parquet sorts columns)
        dates = [date(2026, 1, d) for d in range(1, 11)]
        flat_response = HogQLQueryResponse(
            results=[
                (0, dates, [1.0] * 10),  # series 0: count
                (1, dates, [1.0] * 10),  # series 1: dau
            ],
            columns=["__series_index", "date", "total"],
            types=["Int64", "Array(Date)", "Array(Float64)"],
            hasMore=False,
        )

        with mock.patch(
            "products.endpoints.backend.api.process_query_model",
            return_value=flat_response,
        ):
            mat_resp = self._run_endpoint(endpoint)

        assert mat_resp.status_code == status.HTTP_200_OK
        mat_results = mat_resp.json()["results"]
        assert len(mat_results) >= 2, f"Expected 2+ series in materialized response, got {len(mat_results)}"

        for i, result in enumerate(mat_results):
            assert isinstance(result, dict), f"Series {i}: expected dict, got {type(result).__name__}"
            for field in TRENDS_REQUIRED_FIELDS:
                assert field in result, f"Series {i}: materialized response missing '{field}'"

        # Value assertions: both series should have 10 data points with count 1.0
        for i, result in enumerate(mat_results):
            assert result["data"] == [1.0] * 10, f"Series {i}: unexpected data values: {result['data']}"
            assert result["count"] == 10.0, f"Series {i}: unexpected count: {result['count']}"
