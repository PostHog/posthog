import uuid
from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest import mock

from django.conf import settings

import pytest_asyncio
import temporalio.common
import temporalio.worker
from asgiref.sync import sync_to_async
from rest_framework import status

from posthog.schema import DataWarehouseSyncInterval

from posthog.models.team import Team
from posthog.settings.temporal import DATA_MODELING_TASK_QUEUE
from posthog.sync import database_sync_to_async

from products.data_warehouse.backend.data_load.saved_query_service import get_saved_query_schedule
from products.data_warehouse.backend.models import DataWarehouseModelPath
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
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

    def test_cannot_materialize_non_hogql_query(self):
        """Test that only HogQL queries can be materialized."""
        endpoint = Endpoint.objects.create(
            name="test_trends_query",
            team=self.team,
            query={
                "kind": "TrendsQuery",
                "series": [{"kind": "EventsNode", "event": "$pageview", "math": "total"}],
                "dateRange": {"date_from": "-7d"},
                "interval": "day",
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
        from temporalio.client import ScheduleActionStartWorkflow

        assert isinstance(schedule.action, ScheduleActionStartWorkflow)
        assert schedule.action.id == str(saved_query.id)
        assert schedule.action.task_queue == DATA_MODELING_TASK_QUEUE

        # Verify schedule interval matches sync_frequency_interval
        intervals = schedule.spec.intervals
        assert len(intervals) == 1
        assert intervals[0].every == timedelta(hours=12)

        # Verify schedule policy
        assert schedule.policy.overlap == temporalio.client.ScheduleOverlapPolicy.SKIP

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

    @pytest.mark.skipif(
        not settings.TEMPORAL_HOST or settings.TEMPORAL_HOST == "",
        reason="Temporal not configured for this environment",
    )
    async def test_temporal_workflow_execution_mocked(self, materialized_endpoint, ateam, temporal_client):
        """Test that the Temporal workflow executes and materializes the saved query (mocked)."""
        from posthog.temporal.data_modeling.run_workflow import (
            RunWorkflow,
            RunWorkflowInputs,
            Selector,
            build_dag_activity,
            cleanup_running_jobs_activity,
            create_job_model_activity,
            fail_jobs_activity,
            finish_run_activity,
            run_dag_activity,
            start_run_activity,
        )

        from products.data_warehouse.backend.models.data_modeling_job import DataModelingJob

        saved_query = materialized_endpoint.saved_query
        workflow_id = str(uuid.uuid4())

        inputs = RunWorkflowInputs(
            team_id=ateam.pk,
            select=[Selector(label=saved_query.id.hex, ancestors=0, descendants=0)],
        )

        # Mock materialize_model to avoid actual S3 operations
        async def mock_materialize_model(model_label, team, saved_query, job, *args, **kwargs):
            return ("test_key", mock.MagicMock(), uuid.uuid4())

        with mock.patch("posthog.temporal.data_modeling.run_workflow.materialize_model", mock_materialize_model):
            async with temporalio.worker.Worker(
                temporal_client,
                task_queue=DATA_MODELING_TASK_QUEUE,
                workflows=[RunWorkflow],
                activities=[
                    start_run_activity,
                    build_dag_activity,
                    run_dag_activity,
                    finish_run_activity,
                    create_job_model_activity,
                    fail_jobs_activity,
                    cleanup_running_jobs_activity,
                ],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                # Ensure team exists
                await sync_to_async(Team.objects.get)(pk=ateam.pk)

                # Execute workflow
                await temporal_client.execute_workflow(
                    RunWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=DATA_MODELING_TASK_QUEUE,
                    retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
                    execution_timeout=timedelta(seconds=30),
                )

        # Verify job was created and started successfully
        job = await database_sync_to_async(DataModelingJob.objects.get)(workflow_id=workflow_id)
        assert job is not None
        assert job.team_id == ateam.pk
        # Job should either be running or completed (not failed)
        assert job.status in [DataModelingJob.Status.RUNNING, DataModelingJob.Status.COMPLETED]
