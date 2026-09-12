"""External schema sync action tests."""

import pytest
from posthog.test.base import APIBaseTest
from unittest import mock

from parameterized import parameterized
from temporalio.service import RPCError, RPCStatusCode

from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

pytestmark = [pytest.mark.django_db]


class TestCancelExternalDataSchema(APIBaseTest):
    def _create_schema_with_running_job(self, pipeline_version=None):
        from products.warehouse_sources.backend.facade.models import ExternalDataJob

        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "123"}
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.RUNNING,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )
        job = ExternalDataJob.objects.create(
            team=self.team,
            pipeline=source,
            schema=schema,
            status=ExternalDataJob.Status.RUNNING,
            workflow_id="test-workflow-id",
            pipeline_version=pipeline_version,
        )
        return schema, job

    @mock.patch(
        "products.warehouse_sources.backend.presentation.views.external_data_schema.viewset.finish_row_tracking",
        new_callable=mock.AsyncMock,
    )
    @mock.patch(
        "products.warehouse_sources.backend.presentation.views.external_data_schema.viewset.cancel_external_data_workflow"
    )
    def test_cancel_running_v3_sync_marks_job_failed(self, mock_cancel, mock_finish_row_tracking):
        from products.warehouse_sources.backend.facade.models import ExternalDataJob

        schema, job = self._create_schema_with_running_job(pipeline_version=ExternalDataJob.PipelineVersion.V3)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/cancel/",
        )

        assert response.status_code == 200
        mock_cancel.assert_called_once_with(job.workflow_id)

        job.refresh_from_db()
        schema.refresh_from_db()
        assert job.status == ExternalDataJob.Status.FAILED
        assert job.latest_error == "Sync cancelled by user"
        assert schema.status == ExternalDataSchema.Status.FAILED
        # Nothing will finish the in-flight row counter once the job is Failed, so cancel must.
        mock_finish_row_tracking.assert_awaited_once_with(self.team.pk, str(schema.id))

    @parameterized.expand(
        [
            # v3 loading phase: the extraction workflow completed but the job stays Running while
            # the loader drains batches. Cancel must mark the job Failed (the loader acts on that
            # marker) instead of returning a 400.
            ("workflow_already_finished", "NOT_FOUND"),
            # Transient RPC failure: the Failed marker is durable and absorbing, so the cancel
            # stands and a 500 would strand the user (the job is no longer Running, so a retry
            # can't reach the workflow again).
            ("transient_rpc_failure", "UNAVAILABLE"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.presentation.views.external_data_schema.viewset.finish_row_tracking",
        new_callable=mock.AsyncMock,
    )
    @mock.patch(
        "products.warehouse_sources.backend.presentation.views.external_data_schema.viewset.cancel_external_data_workflow"
    )
    def test_cancel_v3_succeeds_when_cancel_rpc_fails(self, _case, rpc_status_name, mock_cancel, _mock_finish):
        from products.warehouse_sources.backend.facade.models import ExternalDataJob

        schema, job = self._create_schema_with_running_job(pipeline_version=ExternalDataJob.PipelineVersion.V3)
        mock_cancel.side_effect = RPCError("cancel failed", RPCStatusCode[rpc_status_name], b"")

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/cancel/",
        )

        assert response.status_code == 200

        job.refresh_from_db()
        schema.refresh_from_db()
        assert job.status == ExternalDataJob.Status.FAILED
        assert job.latest_error == "Sync cancelled by user"
        assert schema.status == ExternalDataSchema.Status.FAILED

    @parameterized.expand([("v1", "v1-dlt-sync"), ("legacy_null_version", None)])
    @mock.patch(
        "products.warehouse_sources.backend.presentation.views.external_data_schema.viewset.cancel_external_data_workflow"
    )
    def test_cancel_legacy_pipeline_leaves_status_to_the_workflow(self, _case, pipeline_version, mock_cancel):
        # Pre-v3 pipelines: the cancelled workflow records the job's terminal status itself,
        # so the endpoint must not write a Failed marker.
        from products.warehouse_sources.backend.facade.models import ExternalDataJob

        schema, job = self._create_schema_with_running_job(pipeline_version=pipeline_version)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/cancel/",
        )

        assert response.status_code == 200
        mock_cancel.assert_called_once_with(job.workflow_id)

        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.RUNNING
        assert job.latest_error is None

    @parameterized.expand([("v1", "v1-dlt-sync"), ("legacy_null_version", None)])
    @mock.patch(
        "products.warehouse_sources.backend.presentation.views.external_data_schema.viewset.cancel_external_data_workflow"
    )
    def test_cancel_legacy_pipeline_recovers_when_workflow_already_gone(self, _case, pipeline_version, mock_cancel):
        # A workflow that was terminated (not cancelled) never runs the cleanup that writes the
        # terminal status, so the cancel RPC comes back NOT_FOUND. Without recovery the job and
        # schema would stay stuck on Running forever and the schema could never be synced again.

        from products.warehouse_sources.backend.facade.models import ExternalDataJob

        schema, job = self._create_schema_with_running_job(pipeline_version=pipeline_version)
        mock_cancel.side_effect = RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b"")

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/cancel/",
        )

        assert response.status_code == 200

        job.refresh_from_db()
        schema.refresh_from_db()
        assert job.status == ExternalDataJob.Status.FAILED
        assert job.latest_error == "Sync cancelled by user"
        assert schema.status == ExternalDataSchema.Status.FAILED

    @mock.patch(
        "products.warehouse_sources.backend.presentation.views.external_data_schema.viewset.cancel_external_data_workflow"
    )
    def test_cancel_legacy_pipeline_returns_400_on_transient_rpc_error(self, mock_cancel):
        # A transient RPC failure against a possibly-live workflow must not mark the job Failed -
        # the workflow still owns the terminal status, so leave it Running and surface the error.

        from products.warehouse_sources.backend.facade.models import ExternalDataJob

        schema, job = self._create_schema_with_running_job(pipeline_version=ExternalDataJob.PipelineVersion.V1)
        mock_cancel.side_effect = RPCError("temporal unavailable", RPCStatusCode.UNAVAILABLE, b"")

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/cancel/",
        )

        assert response.status_code == 400

        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.RUNNING

    @mock.patch(
        "products.warehouse_sources.backend.presentation.views.external_data_schema.viewset.cancel_external_data_workflow"
    )
    def test_cancel_when_no_running_job(self, mock_cancel):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "123"}
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/cancel/",
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "No running sync to cancel."
        mock_cancel.assert_not_called()

    @parameterized.expand(
        [
            # A trigger that never started a run leaves Running with no job at all.
            ("no_job", None, ExternalDataSchema.Status.FAILED, None),
            # A failed run whose schema repaint was lost leaves Running over a Failed job.
            ("failed_job", "Failed", ExternalDataSchema.Status.FAILED, "the source broke"),
            ("completed_job", "Completed", ExternalDataSchema.Status.COMPLETED, None),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.presentation.views.external_data_schema.viewset.cancel_external_data_workflow"
    )
    def test_cancel_corrects_stale_running_schema(
        self, _case, job_status, expected_schema_status, job_error, mock_cancel
    ):
        # A schema stuck reporting Running with no running job used to 400 on cancel, leaving the
        # user no way to clear the stale status. Cancel must correct it instead.
        from products.warehouse_sources.backend.facade.models import ExternalDataJob

        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "123"}
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.RUNNING,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )
        if job_status is not None:
            ExternalDataJob.objects.create(
                team=self.team,
                pipeline=source,
                schema=schema,
                status=job_status,
                latest_error=job_error,
                workflow_id="test-workflow-id",
                pipeline_version=ExternalDataJob.PipelineVersion.V3,
            )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/cancel/",
        )

        assert response.status_code == 200
        mock_cancel.assert_not_called()

        schema.refresh_from_db()
        assert schema.status == expected_schema_status
        if job_error is not None:
            assert schema.latest_error == job_error


class TestTriggerFailureDoesNotPaintRunning(APIBaseTest):
    def _create_schema(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "123"}
        )
        return ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.FAILED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

    @parameterized.expand([("reload",), ("resync",)])
    @mock.patch(
        "products.warehouse_sources.backend.presentation.views.external_data_schema.sync.trigger_external_data_workflow"
    )
    def test_schema_not_marked_running_when_trigger_fails(self, endpoint, mock_trigger):
        # Painting Running when no workflow started leaves the schema stuck on Running forever
        # (nothing finalizes it) and blocks cancel with "No running sync to cancel."

        schema = self._create_schema()
        mock_trigger.side_effect = RPCError("temporal unavailable", RPCStatusCode.UNAVAILABLE, b"")

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/{endpoint}/",
        )

        assert response.status_code == 400

        schema.refresh_from_db()
        assert schema.status == ExternalDataSchema.Status.FAILED

    @parameterized.expand([("reload",), ("resync",)])
    @mock.patch(
        "products.warehouse_sources.backend.presentation.views.external_data_schema.sync.sync_external_data_job_workflow"
    )
    @mock.patch(
        "products.warehouse_sources.backend.presentation.views.external_data_schema.sync.trigger_external_data_workflow"
    )
    def test_missing_schedule_is_created_so_the_sync_starts(self, endpoint, mock_trigger, mock_create_schedule):
        # A schema with no schedule behind it can't be triggered, and retrying never fixes it. The
        # source-level reload already recovers by creating the schedule; one table must too.

        schema = self._create_schema()
        mock_trigger.side_effect = RPCError("schedule not found", RPCStatusCode.NOT_FOUND, b"")

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/{endpoint}/",
        )

        assert response.status_code == 200
        mock_create_schedule.assert_called_once_with(schema, create=True, should_sync=True)

        schema.refresh_from_db()
        assert schema.status == ExternalDataSchema.Status.RUNNING
