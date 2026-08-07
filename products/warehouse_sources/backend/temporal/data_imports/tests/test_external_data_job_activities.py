from posthog.test.base import BaseTest
from unittest import mock

from django.test import SimpleTestCase

from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.external_data_job import (
    _row_tracking_residual_is_significant,
    trigger_schedule_buffer_one_activity,
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


class TestRowTrackingResidualSignificance(SimpleTestCase):
    @parameterized.expand(
        [
            # Small residuals from estimate drift are the noise we want to stop reporting.
            ("single_row", 1, 500_000, False),
            ("hundreds_of_rows_on_a_big_sync", 291, 1_000_000, False),
            ("below_fraction_floor_on_small_sync", 900, 100, False),
            # Large absolute residuals point at dropped work regardless of the estimate.
            ("large_absolute_residual", 43_415, 5_000_000, True),
            ("at_absolute_threshold", 10_000, 5_000_000, True),
            # A residual that is a large fraction of the estimated total also matters.
            ("half_the_estimate_dropped", 5_000, 5_000, True),
            ("just_over_the_fraction", 2_000, 30_000, True),
            ("just_under_the_fraction", 1_000, 40_000, False),
            # Missing rows_synced falls back to the absolute test only.
            ("no_rows_synced_small", 2_000, None, False),
            ("no_rows_synced_large", 12_000, None, True),
        ]
    )
    def test_only_large_or_high_fraction_residuals_are_significant(
        self, _name: str, rows_tracked: int, rows_synced: int | None, expected: bool
    ):
        assert _row_tracking_residual_is_significant(rows_tracked, rows_synced) is expected
