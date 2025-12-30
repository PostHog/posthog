from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest import mock

from django.utils import timezone

import pytest_asyncio
from asgiref.sync import sync_to_async
from rest_framework import status
from rest_framework.response import Response

from posthog.schema import DataWarehouseSyncInterval, PathsFilter, PathsQuery, PathType, RetentionQuery

from posthog.constants import RETENTION_FIRST_EVER_OCCURRENCE, TREND_FILTER_TYPE_EVENTS
from posthog.settings.temporal import DATA_MODELING_TASK_QUEUE
from posthog.sync import database_sync_to_async

from products.data_warehouse.backend.data_load.saved_query_service import get_saved_query_schedule
from products.data_warehouse.backend.models import DataWarehouseModelPath, DataWarehouseTable
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.endpoints.backend.api import EndpointViewSet
from products.endpoints.backend.models import Endpoint

pytestmark = [pytest.mark.django_db]


class TestEndpointMaterialization(ClickhouseTestMixin, APIBaseTest):
    """Test suite for materialized endpoints."""

    ENDPOINT = "endpoints"

    def setUp(self):
        super().setUp()
        self.sample_hogql_query = {
            "kind": "HogQLQuery",
            "query": "SELECT event, distinct_id FROM events WHERE event = '$pageview' LIMIT 100",
        }
        # Mock sync_saved_query_workflow to avoid Temporal connection
        self.sync_workflow_patcher = mock.patch(
            "products.data_warehouse.backend.data_load.saved_query_service.sync_saved_query_workflow"
        )
        self.mock_sync_workflow = self.sync_workflow_patcher.start()

    def tearDown(self):
        self.sync_workflow_patcher.stop()
        super().tearDown()

    def test_enable_materialization_creates_saved_query(self):
        """Test that enabling materialization creates a SavedQuery."""
        # Create an endpoint
        endpoint = Endpoint.objects.create(
            name="test_materialized_endpoint",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            is_active=True,
        )

        # Verify no saved_query exists yet
        self.assertIsNone(endpoint.saved_query)

        # Update endpoint to enable materialization
        updated_data = {
            "is_materialized": True,
            "sync_frequency": DataWarehouseSyncInterval.FIELD_24HOUR,
        }

        response = self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/", updated_data, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        response_data = response.json()
        self.assertTrue(response_data["is_materialized"])

        # Verify SavedQuery was created
        endpoint.refresh_from_db()
        self.assertIsNotNone(endpoint.saved_query)
        saved_query = endpoint.saved_query
        assert saved_query is not None
        self.assertEqual(saved_query.name, endpoint.name)
        self.assertEqual(saved_query.query, endpoint.query)
        self.assertTrue(saved_query.is_materialized)
        self.assertEqual(saved_query.origin, DataWarehouseSavedQuery.Origin.ENDPOINT)

        # Verify sync_frequency_interval is set
        self.assertEqual(saved_query.sync_frequency_interval, timedelta(hours=24))

        # Verify ModelPath was created
        self.assertTrue(
            DataWarehouseModelPath.objects.filter(team=self.team, saved_query=saved_query).exists(),
            "DataWarehouseModelPath should be created for the saved_query",
        )

    def test_update_sync_frequency_updates_saved_query_sync_interval(self):
        """Test that updating sync_frequency updates the SavedQuery's sync_interval."""
        # Create and materialize an endpoint
        endpoint = Endpoint.objects.create(
            name="test_sync_frequency",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
        )

        # Enable materialization with 24-hour frequency
        self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {
                "is_materialized": True,
                "sync_frequency": DataWarehouseSyncInterval.FIELD_24HOUR,
            },
            format="json",
        )

        endpoint.refresh_from_db()
        saved_query = endpoint.saved_query
        assert saved_query is not None
        self.assertEqual(saved_query.sync_frequency_interval, timedelta(hours=24))

        # Update to 12-hour frequency
        response = self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {
                "is_materialized": True,
                "sync_frequency": DataWarehouseSyncInterval.FIELD_12HOUR,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify sync_interval was updated
        saved_query.refresh_from_db()
        self.assertEqual(saved_query.sync_frequency_interval, timedelta(hours=12))

        # Update to 1-hour frequency
        response = self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {
                "is_materialized": True,
                "sync_frequency": DataWarehouseSyncInterval.FIELD_1HOUR,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify sync_interval was updated
        saved_query.refresh_from_db()
        self.assertEqual(saved_query.sync_frequency_interval, timedelta(hours=1))

    def test_disable_materialization_removes_saved_query(self):
        """Test that disabling materialization removes the SavedQuery."""
        # Create and materialize an endpoint
        endpoint = Endpoint.objects.create(
            name="test_disable_materialization",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
        )

        self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {
                "is_materialized": True,
                "sync_frequency": DataWarehouseSyncInterval.FIELD_24HOUR,
            },
            format="json",
        )

        endpoint.refresh_from_db()
        self.assertIsNotNone(endpoint.saved_query)
        assert endpoint.saved_query is not None
        saved_query_id = endpoint.saved_query.id

        # Disable materialization
        response = self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"is_materialized": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertFalse(response_data["is_materialized"])

        # Verify saved_query is removed from endpoint
        endpoint.refresh_from_db()
        self.assertIsNone(endpoint.saved_query)

        # Verify SavedQuery is soft-deleted
        saved_query = DataWarehouseSavedQuery.objects.get(id=saved_query_id)
        self.assertTrue(saved_query.deleted)

    def test_cannot_materialize_query_with_variables(self):
        """Test that queries with variables cannot be materialized."""
        endpoint = Endpoint.objects.create(
            name="test_variables",
            team=self.team,
            query={
                "kind": "HogQLQuery",
                "query": "SELECT * FROM events WHERE event = {variables.event_name}",
                "variables": {"event_name": {"value": "$pageview"}},
            },
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {
                "is_materialized": True,
                "sync_frequency": DataWarehouseSyncInterval.FIELD_24HOUR,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # The API wraps validation errors in a generic message
        self.assertIn("Failed to update endpoint", response.json()["detail"])

    def test_can_materialize_lifecycle_query(self):
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
        )
        flush_persons_and_events()

        endpoint = Endpoint.objects.create(
            name="test_lifecycle_query",
            team=self.team,
            query={
                "kind": "LifecycleQuery",
                "series": [{"kind": "EventsNode", "event": "$pageview"}],
                "dateRange": {"date_from": "-7d"},
                "interval": "day",
            },
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {
                "is_materialized": True,
                "sync_frequency": DataWarehouseSyncInterval.FIELD_12HOUR,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        endpoint.refresh_from_db()
        self.assertIsNotNone(endpoint.saved_query)
        saved_query = endpoint.saved_query
        assert saved_query is not None
        assert saved_query.query is not None
        self.assertEqual(saved_query.query["kind"], "HogQLQuery")
        self.assertIsInstance(saved_query.query["query"], str)

    def test_can_materialize_stickiness_query(self):
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
        )
        flush_persons_and_events()

        endpoint = Endpoint.objects.create(
            name="test_stickiness_query",
            team=self.team,
            query={
                "kind": "StickinessQuery",
                "series": [{"kind": "EventsNode", "event": "$pageview"}],
                "dateRange": {"date_from": "-7d"},
                "interval": "day",
            },
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {
                "is_materialized": True,
                "sync_frequency": DataWarehouseSyncInterval.FIELD_12HOUR,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        endpoint.refresh_from_db()
        self.assertIsNotNone(endpoint.saved_query)
        saved_query = endpoint.saved_query
        assert saved_query is not None
        assert saved_query.query is not None
        self.assertEqual(saved_query.query["kind"], "HogQLQuery")

    def test_can_materialize_retention_query(self):
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
        )
        flush_persons_and_events()

        endpoint = Endpoint.objects.create(
            name="test_retention_query",
            team=self.team,
            query=RetentionQuery(
                dateRange={"date_from": "2025-01-01", "date_to": "2025-01-08"},
                retentionFilter={
                    "period": "Day",
                    "totalIntervals": 7,
                    "retentionType": RETENTION_FIRST_EVER_OCCURRENCE,
                    "targetEntity": {
                        "id": "$user_signed_up",
                        "name": "$user_signed_up",
                        "type": TREND_FILTER_TYPE_EVENTS,
                    },
                    "returningEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
                },
            ).model_dump(),
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {
                "is_materialized": True,
                "sync_frequency": DataWarehouseSyncInterval.FIELD_12HOUR,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        endpoint.refresh_from_db()
        self.assertIsNotNone(endpoint.saved_query)
        saved_query = endpoint.saved_query
        assert saved_query is not None
        assert saved_query.query is not None
        self.assertEqual(saved_query.query["kind"], "HogQLQuery")

    def test_can_materialize_paths_query(self):
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
        )
        flush_persons_and_events()

        endpoint = Endpoint.objects.create(
            name="test_paths_query",
            team=self.team,
            query=PathsQuery(
                pathsFilter=PathsFilter(
                    includeEventTypes=[PathType.FIELD_PAGEVIEW, PathType.FIELD_SCREEN],
                    excludeEvents=["logout", "https://example.com"],  # URL should be filtered out
                )
            ).model_dump(),
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {
                "is_materialized": True,
                "sync_frequency": DataWarehouseSyncInterval.FIELD_12HOUR,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        endpoint.refresh_from_db()
        self.assertIsNotNone(endpoint.saved_query)
        saved_query = endpoint.saved_query
        assert saved_query is not None
        assert saved_query.query is not None
        self.assertEqual(saved_query.query["kind"], "HogQLQuery")

    def test_materialization_status_in_response(self):
        """Test that materialization status is included in endpoint response."""
        endpoint = Endpoint.objects.create(
            name="test_status",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
        )

        # Before materialization
        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertFalse(response_data["is_materialized"])
        self.assertIn("materialization", response_data)
        self.assertTrue(response_data["materialization"]["can_materialize"])

        # After materialization
        self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {
                "is_materialized": True,
                "sync_frequency": DataWarehouseSyncInterval.FIELD_12HOUR,
            },
            format="json",
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertTrue(response_data["is_materialized"])
        self.assertIn("materialization", response_data)
        self.assertTrue(response_data["materialization"]["can_materialize"])
        self.assertIn("status", response_data["materialization"])
        self.assertIn("sync_frequency", response_data["materialization"])
        self.assertEqual(response_data["materialization"]["sync_frequency"], "12hour")

    def test_materialization_status_endpoint(self):
        """Test the dedicated materialization_status endpoint returns only materialization data."""
        endpoint = Endpoint.objects.create(
            name="test_status_endpoint",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
        )

        # Before materialization - should show can_materialize
        response = self.client.get(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/materialization_status/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertTrue(response_data["can_materialize"])
        self.assertNotIn("name", response_data)
        self.assertNotIn("query", response_data)
        self.assertNotIn("created_by", response_data)

        # Enable materialization
        self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {
                "is_materialized": True,
                "sync_frequency": DataWarehouseSyncInterval.FIELD_6HOUR,
            },
            format="json",
        )

        # After materialization - should show full status
        response = self.client.get(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/materialization_status/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertTrue(response_data["can_materialize"])
        self.assertIn("status", response_data)
        self.assertIn("sync_frequency", response_data)
        self.assertEqual(response_data["sync_frequency"], "6hour")
        self.assertIn("last_materialized_at", response_data)
        self.assertIn("error", response_data)
        # Verify no other endpoint fields are included
        self.assertNotIn("name", response_data)
        self.assertNotIn("query", response_data)
        self.assertNotIn("created_by", response_data)
        self.assertNotIn("description", response_data)

    def test_cache_invalidated_after_query_update(self):
        """Test that updating endpoint query invalidates cache for materialized endpoints."""
        initial_query = {
            "kind": "HogQLQuery",
            "query": "SELECT 1 as value",
        }
        updated_query = {
            "kind": "HogQLQuery",
            "query": "SELECT 2 as value",
        }

        endpoint = Endpoint.objects.create(
            name="query_update_endpoint",
            team=self.team,
            query=initial_query,
            created_by=self.user,
            is_active=True,
        )

        self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {
                "is_materialized": True,
                "sync_frequency": DataWarehouseSyncInterval.FIELD_24HOUR,
            },
            format="json",
        )

        endpoint.refresh_from_db()
        self.assertEqual(endpoint.current_version, 1)
        saved_query = endpoint.saved_query
        assert saved_query is not None
        saved_query.status = DataWarehouseSavedQuery.Status.COMPLETED
        saved_query.last_run_at = timezone.now() - timedelta(minutes=20)
        saved_query.table = DataWarehouseTable.objects.create(
            team=self.team,
            name="query_update_endpoint",
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern="s3://test-bucket/path",
        )
        saved_query.save()

        with mock.patch("products.endpoints.backend.api.EndpointViewSet._execute_query_and_respond") as mock_execute:
            old_cache_time = timezone.now() - timedelta(minutes=30)
            old_cached_response = Response(
                {
                    "results": [[1]],
                    "is_cached": True,
                    "last_refresh": old_cache_time,
                }
            )
            mock_execute.return_value = old_cached_response

            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
                {},
                format="json",
            )

            self.assertEqual(mock_execute.call_count, 2, "Old cache should be detected as stale and refreshed")

        self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"query": updated_query},
            format="json",
        )

        endpoint.refresh_from_db()
        self.assertEqual(endpoint.current_version, 2, "Version should be incremented after query update")

        new_saved_query = endpoint.saved_query
        assert new_saved_query is not None, "Materialization should be re-enabled after query update"
        new_saved_query.status = DataWarehouseSavedQuery.Status.COMPLETED
        new_saved_query.last_run_at = timezone.now()
        new_saved_query.table = DataWarehouseTable.objects.create(
            team=self.team,
            name=f"query_update_endpoint_v2",
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern="s3://test-bucket/path-v2",
        )
        new_saved_query.save()

        with mock.patch("products.endpoints.backend.api.EndpointViewSet._execute_query_and_respond") as mock_execute:
            new_cache_time = timezone.now() - timedelta(minutes=5)
            new_cached_response = Response(
                {
                    "results": [[1]],
                    "is_cached": True,
                    "last_refresh": new_cache_time,
                }
            )
            fresh_response = Response({"results": [[2]], "is_cached": False})

            mock_execute.side_effect = [new_cached_response, fresh_response]

            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
                {},
                format="json",
            )

            self.assertEqual(
                mock_execute.call_count,
                2,
                "Cache from before query update should be stale (older than new materialization)",
            )
            self.assertEqual(
                response.json()["results"], [[2]], "Should return fresh results after query update, not old cache"
            )

    def test_materialized_endpoint_applies_filters_override(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="materialized_filters_endpoint",
            query=self.sample_hogql_query,
            is_materialized=True,
            status=DataWarehouseSavedQuery.Status.COMPLETED,
        )
        saved_query.table = DataWarehouseTable.objects.create(
            team=self.team,
            name="materialized_filters_endpoint",
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern="s3://test-bucket/path",
        )
        saved_query.save()
        endpoint = Endpoint.objects.create(
            name="materialized_filters_endpoint",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            is_active=True,
            saved_query=saved_query,
        )

        with mock.patch.object(EndpointViewSet, "_execute_query_and_respond", return_value=Response({})) as mock_exec:
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run",
                {
                    "filters_override": {
                        "properties": [{"type": "event", "key": "$lib", "operator": "exact", "value": "$web"}]
                    }
                },
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            query_request_data = mock_exec.call_args[0][0]
            query_payload = query_request_data["query"]
            query_sql = query_payload["query"].lower()

            self.assertIn("where", query_sql)
            self.assertIn("$lib", query_sql)
            self.assertEqual(query_payload["kind"], "HogQLQuery")

    def test_stale_materialized_data_uses_inline_execution(self):
        """Test that stale materialized data triggers inline execution instead of using cached table."""
        # Create a materialized endpoint with a saved_query
        now = timezone.now()
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="stale_data_endpoint",
            query=self.sample_hogql_query,
            is_materialized=True,
            status=DataWarehouseSavedQuery.Status.COMPLETED,
            sync_frequency_interval=timedelta(hours=1),
            last_run_at=now - timedelta(hours=2),  # Last run 2 hours ago, sync every 1 hour = stale
        )
        saved_query.table = DataWarehouseTable.objects.create(
            team=self.team,
            name="stale_data_endpoint",
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern="s3://test-bucket/path",
        )
        saved_query.save()

        endpoint = Endpoint.objects.create(
            name="stale_data_endpoint",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            is_active=True,
            saved_query=saved_query,
        )

        # Mock the execution methods to track which path is taken
        with (
            mock.patch.object(
                EndpointViewSet, "_execute_materialized_endpoint", return_value=Response({})
            ) as mock_materialized,
            mock.patch.object(EndpointViewSet, "_execute_inline_endpoint", return_value=Response({})) as mock_inline,
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run",
                {},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            # Should use inline execution because data is stale
            mock_inline.assert_called_once()
            mock_materialized.assert_not_called()

    def test_fresh_materialized_data_uses_materialized_table(self):
        """Test that fresh materialized data uses the materialized table for faster execution."""
        # Create a materialized endpoint with fresh data
        now = timezone.now()
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="fresh_data_endpoint",
            query=self.sample_hogql_query,
            is_materialized=True,
            status=DataWarehouseSavedQuery.Status.COMPLETED,
            sync_frequency_interval=timedelta(hours=1),
            last_run_at=now - timedelta(minutes=30),  # Last run 30 min ago, sync every 1 hour = fresh
        )
        saved_query.table = DataWarehouseTable.objects.create(
            team=self.team,
            name="fresh_data_endpoint",
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern="s3://test-bucket/path",
        )
        saved_query.save()

        endpoint = Endpoint.objects.create(
            name="fresh_data_endpoint",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            is_active=True,
            saved_query=saved_query,
        )

        # Mock the execution methods to track which path is taken
        with (
            mock.patch.object(
                EndpointViewSet, "_execute_materialized_endpoint", return_value=Response({})
            ) as mock_materialized,
            mock.patch.object(EndpointViewSet, "_execute_inline_endpoint", return_value=Response({})) as mock_inline,
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run",
                {},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            # Should use materialized table because data is fresh
            mock_materialized.assert_called_once()
            mock_inline.assert_not_called()


@pytest.mark.asyncio
class TestEndpointMaterializationTemporal:
    """Test suite for endpoint materialization with Temporal workflows."""

    @pytest_asyncio.fixture
    async def materialized_endpoint(self, ateam, endpoint):
        """Create a materialized endpoint with saved_query."""
        saved_query = await database_sync_to_async(DataWarehouseSavedQuery.objects.create)(
            team=ateam,
            name=endpoint.name,
            query=endpoint.query,
            is_materialized=True,
            sync_frequency_interval=timedelta(hours=12),
            origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
        )
        saved_query.columns = await sync_to_async(saved_query.get_columns)()
        await sync_to_async(saved_query.save)()

        await database_sync_to_async(DataWarehouseModelPath.objects.create_from_saved_query)(saved_query)

        endpoint.saved_query = saved_query
        await sync_to_async(endpoint.save)()

        yield endpoint

    async def test_saved_query_temporal_schedule_created(self, materialized_endpoint):
        """Test that a Temporal schedule is created for the SavedQuery."""
        saved_query = materialized_endpoint.saved_query
        assert saved_query is not None

        # Get the schedule that should be created
        schedule = get_saved_query_schedule(saved_query)

        # Verify schedule configuration
        from temporalio.client import ScheduleActionStartWorkflow, ScheduleOverlapPolicy

        assert isinstance(schedule.action, ScheduleActionStartWorkflow)
        assert schedule.action.id == str(saved_query.id)
        assert schedule.action.task_queue == DATA_MODELING_TASK_QUEUE

        # Verify schedule interval matches sync_frequency_interval
        intervals = schedule.spec.intervals
        assert len(intervals) == 1
        assert intervals[0].every == timedelta(hours=12)

        # Verify schedule policy
        assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP

    async def test_sync_frequency_affects_schedule_interval(self, materialized_endpoint):
        """Test that different sync_frequency values create schedules with correct intervals."""
        saved_query = materialized_endpoint.saved_query

        # Test 1-hour frequency
        saved_query.sync_frequency_interval = timedelta(hours=1)
        schedule = get_saved_query_schedule(saved_query)
        assert schedule.spec.intervals[0].every == timedelta(hours=1)
        assert schedule.spec.jitter == timedelta(minutes=1)

        # Test 12-hour frequency
        saved_query.sync_frequency_interval = timedelta(hours=12)
        schedule = get_saved_query_schedule(saved_query)
        assert schedule.spec.intervals[0].every == timedelta(hours=12)
        assert schedule.spec.jitter == timedelta(minutes=30)

        # Test 24-hour frequency
        saved_query.sync_frequency_interval = timedelta(hours=24)
        schedule = get_saved_query_schedule(saved_query)
        assert schedule.spec.intervals[0].every == timedelta(hours=24)
        assert schedule.spec.jitter == timedelta(hours=1)
