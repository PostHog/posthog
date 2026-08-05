from posthog.test.base import BaseTest
from unittest import mock

from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.external_data_job import (
    SCHEMA_FAILURE_STREAK_PAUSE_THRESHOLD,
    UpdateExternalDataJobStatusInputs,
    trigger_schedule_buffer_one_activity,
    update_external_data_job_model,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


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


class TestUpdateExternalDataJobModelActivityFailureStreak(BaseTest):
    """A table-scoped Postgres failure (e.g. a permission or column error) never matches the
    connection-level non-retryable patterns, so without a separate counter the schema stays
    enabled and the schedule re-runs and re-fails it forever."""

    def _make_schema_and_job(
        self, consecutive_failure_count: int
    ) -> tuple[ExternalDataSource, ExternalDataSchema, ExternalDataJob]:
        source = ExternalDataSource.objects.create(team=self.team, source_type=ExternalDataSourceType.POSTGRES)
        schema = ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="table",
            should_sync=True,
            consecutive_failure_count=consecutive_failure_count,
        )
        job = ExternalDataJob.objects.create(
            team=self.team, pipeline=source, schema=schema, status=ExternalDataJob.Status.RUNNING, rows_synced=0
        )
        return source, schema, job

    def _run_failed(
        self, source: ExternalDataSource, schema: ExternalDataSchema, job: ExternalDataJob, internal_error: str
    ) -> mock.MagicMock:
        inputs = UpdateExternalDataJobStatusInputs(
            team_id=self.team.id,
            job_id=str(job.id),
            schema_id=str(schema.id),
            source_id=str(source.id),
            status=ExternalDataJob.Status.FAILED,
            internal_error=internal_error,
            latest_error=internal_error,
        )
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.external_data_job.update_should_sync"
        ) as mock_update_should_sync:
            ActivityEnvironment().run(update_external_data_job_model, inputs)
        return mock_update_should_sync

    @parameterized.expand(
        [
            ("first_failure", 0, SCHEMA_FAILURE_STREAK_PAUSE_THRESHOLD - 1),
            (
                "one_below_threshold",
                SCHEMA_FAILURE_STREAK_PAUSE_THRESHOLD - 2,
                SCHEMA_FAILURE_STREAK_PAUSE_THRESHOLD - 1,
            ),
        ]
    )
    def test_unclassified_failure_increments_streak_without_pausing_below_threshold(
        self, _name: str, starting_count: int, expected_count: int
    ) -> None:
        source, schema, job = self._make_schema_and_job(consecutive_failure_count=starting_count)

        mock_update_should_sync = self._run_failed(
            source, schema, job, "permission denied reading table account_workout_exercise"
        )

        mock_update_should_sync.assert_not_called()
        schema.refresh_from_db()
        assert schema.consecutive_failure_count == expected_count
        assert schema.should_sync is True

    def test_unclassified_failure_pauses_schema_once_streak_reaches_threshold(self) -> None:
        source, schema, job = self._make_schema_and_job(
            consecutive_failure_count=SCHEMA_FAILURE_STREAK_PAUSE_THRESHOLD - 1
        )

        mock_update_should_sync = self._run_failed(source, schema, job, "permission denied reading table housings")

        mock_update_should_sync.assert_called_once_with(
            schema_id=str(schema.id), team_id=self.team.id, should_sync=False
        )
        schema.refresh_from_db()
        assert schema.consecutive_failure_count == SCHEMA_FAILURE_STREAK_PAUSE_THRESHOLD

    def test_successful_run_resets_failure_streak(self) -> None:
        source, schema, job = self._make_schema_and_job(
            consecutive_failure_count=SCHEMA_FAILURE_STREAK_PAUSE_THRESHOLD - 1
        )
        inputs = UpdateExternalDataJobStatusInputs(
            team_id=self.team.id,
            job_id=str(job.id),
            schema_id=str(schema.id),
            source_id=str(source.id),
            status=ExternalDataJob.Status.COMPLETED,
            internal_error=None,
            latest_error=None,
        )

        ActivityEnvironment().run(update_external_data_job_model, inputs)

        schema.refresh_from_db()
        assert schema.consecutive_failure_count == 0
