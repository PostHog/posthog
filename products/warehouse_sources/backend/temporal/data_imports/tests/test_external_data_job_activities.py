import asyncio

from posthog.test.base import BaseTest
from unittest import mock

from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
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


class TestUpdateExternalDataJobModelActivity(BaseTest):
    def test_leftover_tracked_rows_on_completed_job_are_not_captured_as_an_exception(self) -> None:
        # rows_to_sync is a pre-extraction COUNT(*) estimate that can race with concurrent
        # changes on the source table, so a small leftover on a completed job is expected and
        # must not be reported to error tracking as a bug.
        env = ActivityEnvironment()
        inputs = UpdateExternalDataJobStatusInputs(
            team_id=self.team.id,
            job_id="019fde98-0727-0000-3f05-9991b4c84155",
            schema_id="019fde98-0727-0000-3f05-9991b4c84156",
            source_id="019fde98-0727-0000-3f05-9991b4c84157",
            status=ExternalDataJob.Status.COMPLETED,
            internal_error=None,
            latest_error=None,
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.external_data_job.get_rows",
                return_value=1,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.external_data_job.finish_row_tracking"
            ) as mock_finish_row_tracking,
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.external_data_job.capture_exception"
            ) as mock_capture_exception,
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.external_data_job.update_external_job_status"
            ) as mock_update_job_status,
        ):
            asyncio.run(env.run(update_external_data_job_model, inputs))

        mock_capture_exception.assert_not_called()
        mock_finish_row_tracking.assert_called_once_with(self.team.id, inputs.schema_id)
        mock_update_job_status.assert_called_once()
