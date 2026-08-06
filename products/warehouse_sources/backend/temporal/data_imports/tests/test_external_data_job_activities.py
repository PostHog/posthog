import pytest
from posthog.test.base import BaseTest
from unittest import mock

from asgiref.sync import sync_to_async
from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.external_data_job import (
    UpdateExternalDataJobStatusInputs,
    trigger_schedule_buffer_one_activity,
    update_external_data_job_model,
)


class TestTriggerScheduleBufferOneActivity(BaseTest):
    @parameterized.expand([("billable", True), ("non_billable", False)])
    def test_worker_shutdown_retry_keeps_the_runs_billable_flag(self, _name: str, billable: bool):
        source = ExternalDataSource.objects.create(team=self.team)
        schema = ExternalDataSchema.objects.create(team=self.team, source=source, name="table")

        env = ActivityEnvironment()
        ExternalDataJob.objects.create(
            team=self.team,
            pipeline=source,
            schema=schema,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
            billable=billable,
            workflow_id=env.info.workflow_id,
            workflow_run_id=env.info.workflow_run_id,
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.external_data_job.sync_connect"
            ) as mock_connect,
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.external_data_job.trigger_schedule_buffer_one"
            ) as mock_trigger_schedule,
        ):
            client = mock.AsyncMock()
            mock_connect.return_value = client

            env.run(trigger_schedule_buffer_one_activity, str(schema.id))

        if billable:
            mock_trigger_schedule.assert_called_once_with(mock.ANY, str(schema.id))
            client.start_workflow.assert_not_called()
            return

        # The schedule's stored action is always billable, so a non-billable run has to resume ad-hoc.
        mock_trigger_schedule.assert_not_called()
        inputs = client.start_workflow.call_args.args[1]
        assert isinstance(inputs, ExternalDataWorkflowInputs)
        assert inputs.billable is False
        assert inputs.external_data_schema_id == schema.id


@pytest.mark.parametrize(
    "pipeline_version, sync_type, has_loaded_before, expected_billable",
    [
        # The shape that keeps its charge: the retrigger resumes from a per-batch watermark
        (ExternalDataJob.PipelineVersion.V2, ExternalDataSchema.SyncType.INCREMENTAL, True, True),
        (ExternalDataJob.PipelineVersion.V2, ExternalDataSchema.SyncType.APPEND, True, True),
        # A cut-short v2 first sync also keeps it: its committed chunks survive on S3 and the
        # retrigger merges from the persisted watermark, so these rows are extracted exactly once
        (ExternalDataJob.PipelineVersion.V2, ExternalDataSchema.SyncType.INCREMENTAL, False, True),
        # A full refresh restarts, so the retrigger re-extracts and re-bills these rows
        (ExternalDataJob.PipelineVersion.V2, ExternalDataSchema.SyncType.FULL_REFRESH, True, False),
        (ExternalDataJob.PipelineVersion.V2, ExternalDataSchema.SyncType.FULL_REFRESH, False, False),
        # Thousands of live schemas carry no sync_type and replace their table every run
        (ExternalDataJob.PipelineVersion.V2, None, True, False),
        # v3 stages its watermark until the final batch, which a cut-short run never sends
        (ExternalDataJob.PipelineVersion.V3, ExternalDataSchema.SyncType.INCREMENTAL, True, False),
        (ExternalDataJob.PipelineVersion.V3, ExternalDataSchema.SyncType.INCREMENTAL, False, False),
    ],
)
# transaction=True: the activity writes through database_sync_to_async_pool, which runs off this
# thread on its own connection and so only sees committed rows.
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_shutdown_runs_charge_drops_unless_the_retrigger_resumes(
    team,
    pipeline_version: ExternalDataJob.PipelineVersion,
    sync_type: ExternalDataSchema.SyncType | None,
    has_loaded_before: bool,
    expected_billable: bool,
):
    source = await sync_to_async(ExternalDataSource.objects.create)(team=team)
    table = (
        await sync_to_async(DataWarehouseTable.objects.create)(team=team, name="table", format="DeltaS3Wrapper")
        if has_loaded_before
        else None
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team,
        source=source,
        name="table",
        sync_type=sync_type,
        table=table,
        initial_sync_complete=has_loaded_before,
    )
    job = await sync_to_async(ExternalDataJob.objects.create)(
        team=team,
        pipeline=source,
        schema=schema,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=100,
        billable=True,
        pipeline_version=pipeline_version,
    )

    await ActivityEnvironment().run(
        update_external_data_job_model,
        UpdateExternalDataJobStatusInputs(
            team_id=team.pk,
            job_id=str(job.id),
            schema_id=str(schema.id),
            source_id=str(source.id),
            status=ExternalDataJob.Status.COMPLETED,
            internal_error=None,
            latest_error=None,
            mark_non_billable=True,
        ),
    )

    await sync_to_async(job.refresh_from_db)()
    assert job.status == ExternalDataJob.Status.COMPLETED
    assert job.billable is expected_billable
