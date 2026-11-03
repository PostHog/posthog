import uuid
import dataclasses
from datetime import timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    PersonPropertyBackfillActivityInputs,
    PersonPropertyFailedRunInputs,
    PersonPropertySyncActivityInputs,
    PersonPropertySyncRunRecord,
    PersonPropertySyncSource,
)
from products.warehouse_sources.backend.temporal.data_imports.person_property_backfill_job import (
    PERSON_PROPERTY_BACKFILL_ACTIVITIES,
    RECORD_FAILED_RUN_PATCH,
    BackfillWarehousePersonPropertiesWorkflow,
    backfill_warehouse_person_properties_activity,
    record_failed_person_property_backfill_runs_activity,
)
from products.warehouse_sources.backend.temporal.data_imports.person_property_sync_job import (
    PERSON_PROPERTY_SYNC_ACTIVITIES,
    SyncWarehousePersonPropertiesWorkflow,
    sync_warehouse_person_properties_activity,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.person_property_sync_job"


class TestSyncWarehousePersonPropertiesActivityCapturesFailureContext:
    """A failed run is only attributable to a source/schema in error tracking if the captured
    exception carries that context; a bare capture_exception(e) loses it."""

    @patch(f"{MODULE}.capture_exception")
    @patch(f"{MODULE}.record_failed_runs", new_callable=AsyncMock)
    @patch(f"{MODULE}.record_started_runs", new_callable=AsyncMock)
    @patch(f"{MODULE}.run_person_property_sync", new_callable=AsyncMock)
    @patch(f"{MODULE}.Heartbeater")
    async def test_capture_exception_receives_source_and_schema_context(
        self,
        mock_heartbeater_cls: MagicMock,
        mock_run_sync: AsyncMock,
        _mock_record_started: AsyncMock,
        _mock_record_failed: AsyncMock,
        mock_capture_exception: MagicMock,
    ) -> None:
        mock_heartbeater_cls.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_heartbeater_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        error = ConnectionError("failed to connect to all addresses")
        mock_run_sync.side_effect = error

        inputs = PersonPropertySyncActivityInputs(
            team_id=1,
            schema_id=uuid.uuid4(),
            source_id=uuid.uuid4(),
            job_id="job-1",
            source_type="Stripe",
            schema_name="public.charges",
            last_synced_at=None,
        )

        with pytest.raises(ConnectionError):
            await ActivityEnvironment().run(sync_warehouse_person_properties_activity, inputs)

        mock_capture_exception.assert_called_once_with(error, inputs.properties_to_log)
        captured_properties = mock_capture_exception.call_args[0][1]
        assert captured_properties["source_type"] == "Stripe"
        assert captured_properties["schema_name"] == "public.charges"


HOOKS = "products.warehouse_sources.backend.temporal.data_imports.external_product_hooks"


@activity.defn(name="sync_warehouse_person_properties_activity")
async def _sync_activity_killed_by_worker_shutdown(_inputs: PersonPropertySyncActivityInputs) -> dict:
    raise ApplicationError("Worker is shutting down", type="WorkerShutdown", non_retryable=True)


@activity.defn(name="backfill_warehouse_person_properties_activity")
async def _backfill_activity_killed_by_worker_shutdown(inputs: PersonPropertyBackfillActivityInputs) -> dict:
    assert inputs.workflow_records_failure
    raise ApplicationError("Worker is shutting down", type="WorkerShutdown", non_retryable=True)


@pytest.mark.parametrize(
    "workflow_cls,replaced_activity,killed_activity,real_activities,inputs,expected_job_id",
    [
        (
            SyncWarehousePersonPropertiesWorkflow,
            sync_warehouse_person_properties_activity,
            _sync_activity_killed_by_worker_shutdown,
            PERSON_PROPERTY_SYNC_ACTIVITIES,
            PersonPropertySyncActivityInputs(
                team_id=1,
                schema_id=None,
                source_id=None,
                job_id="job-1",
                source_type="saved_query",
                schema_name="example_view",
                last_synced_at=None,
                saved_query_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
            ),
            "job-1",
        ),
        (
            BackfillWarehousePersonPropertiesWorkflow,
            backfill_warehouse_person_properties_activity,
            _backfill_activity_killed_by_worker_shutdown,
            PERSON_PROPERTY_BACKFILL_ACTIVITIES,
            PersonPropertyBackfillActivityInputs(
                team_id=1,
                schema_id=None,
                source_type="saved_query",
                schema_name="example_view",
                trigger="manual",
                saved_query_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
            ),
            None,
        ),
    ],
)
async def test_run_is_marked_failed_when_the_activity_dies_without_its_own_handler(
    workflow_cls, replaced_activity, killed_activity, real_activities, inputs, expected_job_id
) -> None:
    recorded: list[PersonPropertySyncRunRecord] = []
    source = PersonPropertySyncSource(
        source_id="00000000-0000-4000-8000-000000000002",
        definition_id="00000000-0000-4000-8000-000000000003",
        key_column="distinct_id",
        column_property_map={"plan": "plan_name"},
    )
    other_activities = [a for a in real_activities if a is not replaced_activity]
    task_queue = str(uuid.uuid4())

    with (
        patch(f"{HOOKS}._person_property_sync_sources_resolver", lambda _team_id, _binding: [source]),
        patch(f"{HOOKS}._person_property_sync_recorder", recorded.append),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[workflow_cls],
                activities=[killed_activity, *other_activities],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                with pytest.raises(WorkflowFailureError):
                    await environment.client.execute_workflow(
                        workflow_cls.run, inputs, id=str(uuid.uuid4()), task_queue=task_queue
                    )

    failed = [r for r in recorded if r.status == "failed"]
    assert len(failed) == 1
    assert failed[0].source_id == source.source_id
    assert failed[0].job_id == expected_job_id
    assert (failed[0].error or "").startswith("This run was interrupted before it finished.")
    assert failed[0].finished_at
    assert failed[0].count_failure is False


@workflow.defn(name="sync-warehouse-person-properties")
class _PrePatchSyncWorkflow:
    @workflow.run
    async def run(self, inputs: PersonPropertySyncActivityInputs) -> None:
        await workflow.execute_activity(
            "sync_warehouse_person_properties_activity",
            inputs,
            start_to_close_timeout=timedelta(hours=6),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@workflow.defn(name="backfill-warehouse-person-properties")
class _PrePatchBackfillWorkflow:
    @workflow.run
    async def run(self, inputs: PersonPropertyBackfillActivityInputs) -> None:
        await workflow.execute_activity(
            "backfill_warehouse_person_properties_activity",
            inputs,
            start_to_close_timeout=timedelta(hours=6),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@activity.defn(name="record_failed_person_property_backfill_runs_activity")
async def _discard_backfill_failure(_inputs: PersonPropertyFailedRunInputs) -> None:
    pass


@workflow.defn(name="backfill-warehouse-person-properties")
class _BeforeInterruptionRetryBackfillWorkflow:
    @workflow.run
    async def run(self, inputs: PersonPropertyBackfillActivityInputs) -> None:
        started_at = workflow.now()
        records_failure = workflow.patched(RECORD_FAILED_RUN_PATCH)
        try:
            await workflow.execute_activity(
                backfill_warehouse_person_properties_activity,
                dataclasses.replace(inputs, workflow_records_failure=records_failure),
                start_to_close_timeout=timedelta(hours=6),
                heartbeat_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except ActivityError:
            if records_failure:
                await workflow.execute_activity(
                    record_failed_person_property_backfill_runs_activity,
                    PersonPropertyFailedRunInputs(
                        team_id=inputs.team_id,
                        schema_id=inputs.schema_id,
                        saved_query_id=inputs.saved_query_id,
                        job_id=None,
                        trigger=inputs.trigger,
                        started_at=started_at.isoformat(),
                        error="This run was interrupted before it finished. Click Backfill to try again.",
                    ),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            raise


@pytest.mark.parametrize(
    "pre_patch_workflow,workflow_cls,killed_activity,inputs",
    [
        (
            _PrePatchSyncWorkflow,
            SyncWarehousePersonPropertiesWorkflow,
            _sync_activity_killed_by_worker_shutdown,
            PersonPropertySyncActivityInputs(
                team_id=1,
                schema_id=None,
                source_id=None,
                job_id="job-1",
                source_type="saved_query",
                schema_name="example_view",
                last_synced_at=None,
                saved_query_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
            ),
        ),
        (
            _PrePatchBackfillWorkflow,
            BackfillWarehousePersonPropertiesWorkflow,
            _backfill_activity_killed_by_worker_shutdown,
            PersonPropertyBackfillActivityInputs(
                team_id=1,
                schema_id=None,
                source_type="saved_query",
                schema_name="example_view",
                trigger="manual",
                saved_query_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
            ),
        ),
        (
            _BeforeInterruptionRetryBackfillWorkflow,
            BackfillWarehousePersonPropertiesWorkflow,
            _backfill_activity_killed_by_worker_shutdown,
            PersonPropertyBackfillActivityInputs(
                team_id=1,
                schema_id=None,
                source_type="saved_query",
                schema_name="example_view",
                trigger="manual",
                saved_query_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
            ),
        ),
    ],
)
async def test_failed_history_from_before_the_failed_run_record_still_replays(
    pre_patch_workflow, workflow_cls, killed_activity, inputs
) -> None:
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[pre_patch_workflow],
            activities=[killed_activity, _discard_backfill_failure],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await environment.client.start_workflow(
                pre_patch_workflow.run, inputs, id=str(uuid.uuid4()), task_queue=task_queue
            )
            with pytest.raises(WorkflowFailureError):
                await handle.result()
            history = await handle.fetch_history()

    await Replayer(workflows=[workflow_cls], workflow_runner=UnsandboxedWorkflowRunner()).replay_workflow(history)


async def test_sync_activity_deadline_leaves_time_to_record_the_failure_before_the_workflow_deadline() -> None:
    inputs = PersonPropertySyncActivityInputs(
        team_id=1,
        schema_id=None,
        source_id=None,
        job_id="job-deadline",
        source_type="saved_query",
        schema_name="example_view",
        last_synced_at=None,
        saved_query_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
    )
    other_activities = [
        a for a in PERSON_PROPERTY_SYNC_ACTIVITIES if a is not sync_warehouse_person_properties_activity
    ]
    task_queue = str(uuid.uuid4())
    with (
        patch(f"{HOOKS}._person_property_sync_sources_resolver", lambda _team_id, _binding: []),
        patch(f"{HOOKS}._person_property_sync_recorder", lambda _record: None),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[SyncWarehousePersonPropertiesWorkflow],
                activities=[_sync_activity_killed_by_worker_shutdown, *other_activities],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                handle = await environment.client.start_workflow(
                    SyncWarehousePersonPropertiesWorkflow.run,
                    inputs,
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    execution_timeout=timedelta(hours=6),
                )
                with pytest.raises(WorkflowFailureError):
                    await handle.result()
                history = await handle.fetch_history()

    scheduled = [
        e.activity_task_scheduled_event_attributes
        for e in history.events
        if e.activity_task_scheduled_event_attributes.activity_type.name == "sync_warehouse_person_properties_activity"
    ]
    assert len(scheduled) == 1
    # The recorder needs up to 3 attempts of 5 minutes after the sync activity gives up.
    deadline = scheduled[0].schedule_to_close_timeout.ToTimedelta()
    assert timedelta(0) < deadline <= timedelta(hours=6) - timedelta(minutes=15)
