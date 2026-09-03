import asyncio

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from django.test import SimpleTestCase

from parameterized import parameterized
from temporalio.exceptions import ApplicationError, CancelledError
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team
from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.external_data_job import (
    CANCELLED_RUN_MESSAGE,
    UNEXPECTED_ERROR_MESSAGE,
    UpdateExternalDataJobStatusInputs,
    _customer_facing_error,
    _is_app_db_failure,
    trigger_schedule_buffer_one_activity,
    update_external_data_job_model,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCustomerFacingError(SimpleTestCase):
    @parameterized.expand(
        [
            # Temporal wraps a retryable REST exhaustion / connection drop as an ApplicationError
            # whose str() is "<ClassName>: <message>". The customer-facing latest_error must be the
            # message alone, not the internal class name.
            ("rest_retryable", "RESTClientRetryableError", "HTTP 429 for https://api.example.com/usage"),
            ("driver_drop", "OperationalError", "connection failed: server closed the connection unexpectedly"),
        ]
    )
    def test_strips_leaked_internal_exception_class_name(self, _name: str, exc_type: str, message: str) -> None:
        assert _customer_facing_error(ApplicationError(message, type=exc_type)) == message

    def test_falls_back_to_str_when_cause_has_no_message(self) -> None:
        assert _customer_facing_error(ValueError("connection reset")) == "connection reset"

    def test_cancelled_run_does_not_surface_the_bare_cancelled_word(self) -> None:
        # A superseded/paused run cancels the activity; its cause is a CancelledError whose message
        # is the bare word "Cancelled". The customer must get a readable message instead.
        result = _customer_facing_error(CancelledError())
        assert result == CANCELLED_RUN_MESSAGE
        assert result != "Cancelled"

    def test_missing_cause_does_not_show_the_customer_none(self) -> None:
        assert _customer_facing_error(None) == UNEXPECTED_ERROR_MESSAGE


class TestIsAppDbFailure(SimpleTestCase):
    @parameterized.expand(
        [
            # A pooled connection left on a demoted standby by a failover. Ours, and it clears.
            ("failover", "InternalError", "cannot execute UPDATE in a read-only transaction", True),
            # Django reports a corrupted index under the same class name. That one is a defect, so
            # it must not be labeled a passing outage and told to wait for the next run.
            ("corrupted_index", "InternalError", 'index "posthog_team_pkey" contains a zero page', False),
            # psycopg raises the source-side read-only condition under its own class name, which is
            # how a customer's write-on-read view stays the customer's to fix.
            ("source_side", "ReadOnlySqlTransaction", "cannot execute INSERT in a read-only transaction", False),
        ]
    )
    def test_only_the_failover_case_counts_as_ours(
        self, _name: str, exc_type: str, message: str, expected: bool
    ) -> None:
        # str(ApplicationError) is what the workflow stores as internal_error, so build the input
        # the same way rather than hand-writing the prefix this depends on.
        assert _is_app_db_failure(str(ApplicationError(message, type=exc_type))) is expected


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


# transaction=True commits the fixture rows: the activity resolves the schema through
# database_sync_to_async_pool, whose pool-thread connection can't see a test transaction.
@pytest.mark.django_db(transaction=True)
def test_failed_finalization_with_no_job_resets_stale_running_schema() -> None:
    # When an early activity fails before the job row is committed, no later finalization can
    # repaint the schema, so the Running status painted at trigger time would stick forever.
    org = Organization.objects.create(name="org")
    team = Team.objects.create(organization=org, name="team")
    source = ExternalDataSource.objects.create(team=team)
    schema = ExternalDataSchema.objects.create(
        team=team, source=source, name="table", status=ExternalDataSchema.Status.RUNNING
    )

    env = ActivityEnvironment()
    inputs = UpdateExternalDataJobStatusInputs(
        team_id=team.id,
        job_id=None,
        schema_id=str(schema.id),
        source_id=str(source.id),
        status=ExternalDataJob.Status.FAILED,
        internal_error=None,
        latest_error="could not create the sync job",
        workflow_run_id="run-id-with-no-job",
    )

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.external_data_job.get_rows",
            return_value=0,
        ),
        mock.patch("products.warehouse_sources.backend.temporal.data_imports.external_data_job.finish_row_tracking"),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.external_data_job.capture_exception"
        ) as mock_capture_exception,
    ):
        asyncio.run(env.run(update_external_data_job_model, inputs))

    mock_capture_exception.assert_not_called()
    schema.refresh_from_db()
    assert schema.status == ExternalDataSchema.Status.FAILED
    assert schema.latest_error == "could not create the sync job"


# transaction=True for the same reason as the test above: the activity resolves the source through
# database_sync_to_async_pool, and the pool thread's connection can't see a test transaction.
@parameterized.expand(
    [
        # A customer relation whose own definition writes while we read it (a view or trigger that
        # refreshes a materialized view). psycopg raises it on the source connection, so it reaches
        # finalization under its own class name, and both the friendly message and the disable are
        # correct.
        ("raised_by_the_source", "ReadOnlySqlTransaction", True),
        # The identical SQLSTATE 25006 wording from our own app DB after a primary failover, which
        # Django reports as InternalError. Nothing is wrong with the source, and disabling makes the
        # customer re-enable a sync our outage stopped.
        ("raised_by_our_app_db", "InternalError", False),
    ]
)
@pytest.mark.django_db(transaction=True)
def test_read_only_transaction_disables_the_schema_only_when_the_source_raised_it(
    _name: str, exc_type: str, expect_disabled: bool
) -> None:
    org = Organization.objects.create(name="org")
    team = Team.objects.create(organization=org, name="team")
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES.value)
    schema = ExternalDataSchema.objects.create(team=team, source=source, name="table")
    job = ExternalDataJob.objects.create(
        team=team, pipeline=source, schema=schema, status=ExternalDataJob.Status.RUNNING, rows_synced=0
    )

    env = ActivityEnvironment()
    inputs = UpdateExternalDataJobStatusInputs(
        team_id=team.id,
        job_id=str(job.id),
        schema_id=str(schema.id),
        source_id=str(source.id),
        status=ExternalDataJob.Status.FAILED,
        internal_error=str(ApplicationError("cannot execute UPDATE in a read-only transaction", type=exc_type)),
        latest_error="cannot execute UPDATE in a read-only transaction",
    )

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.external_data_job.get_rows", return_value=0
        ),
        mock.patch("products.warehouse_sources.backend.temporal.data_imports.external_data_job.finish_row_tracking"),
        mock.patch("products.warehouse_sources.backend.temporal.data_imports.external_data_job.capture_exception"),
        mock.patch("posthoganalytics.capture"),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.external_data_job.update_should_sync"
        ) as mock_update_should_sync,
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.external_data_job.update_external_job_status"
        ) as mock_update_job_status,
    ):
        asyncio.run(env.run(update_external_data_job_model, inputs))

    assert mock_update_should_sync.called is expect_disabled
    customer_message = mock_update_job_status.call_args.kwargs["latest_error"] or ""
    assert ("tries to write to your database" in customer_message) is expect_disabled
