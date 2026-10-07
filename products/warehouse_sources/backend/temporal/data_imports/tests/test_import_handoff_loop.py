import json
import uuid
import base64
import logging
import dataclasses
from concurrent.futures import ThreadPoolExecutor

import pytest
from unittest import mock

from temporalio import activity
from temporalio.client import WorkflowFailureError, WorkflowHistory
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from posthog.temporal.common.shutdown import WorkerShuttingDownError
from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.temporal.data_imports import external_data_job as workflow_module
from products.warehouse_sources.backend.temporal.data_imports.external_data_job import (
    WORKER_RESTART_ERROR_MESSAGE,
    ExternalDataJobWorkflow,
    UpdateExternalDataJobStatusInputs,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.typings import PipelineResult
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.acquire_v3_lock import (
    AcquireV3LockActivityInputs,
    AcquireV3LockActivityOutputs,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (
    CreateExternalDataJobModelActivityInputs,
    CreateExternalDataJobModelActivityOutputs,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
    ImportDataActivityInputs,
)

_JOB_ID = "01960000-0000-0000-0000-000000000000"
_TASK_QUEUE = "test-import-handoff-loop"

# What one attempt of the import activity does.
HANDOFF = "handoff"
OLD_WORKER_HANDOFF = "old_worker_handoff"
FAIL = "fail"
SUCCEED = "succeed"


@pytest.fixture(autouse=True)
def _workflow_logs_at_info(caplog):
    # A bad logger call is inert below INFO and wedges the workflow task in production.
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    caplog.set_level(logging.INFO, logger="temporalio.activity")


@dataclasses.dataclass(frozen=True, kw_only=True)
class _WorkflowRun:
    import_inputs: list[ImportDataActivityInputs]
    import_attempts: list[int]
    updates: list[UpdateExternalDataJobStatusInputs]
    buffer_one_triggers: int
    handoffs_recorded: list[int]
    history: WorkflowHistory
    failed: bool


def _activities(
    script: list[str],
    *,
    handoffs_are_free: bool,
    import_inputs: list[ImportDataActivityInputs],
    import_attempts: list[int],
    updates: list[UpdateExternalDataJobStatusInputs],
    buffer_one: list[str],
) -> list:
    @activity.defn(name="acquire_v3_pipeline_lock_activity")
    async def acquire_lock(inputs: AcquireV3LockActivityInputs) -> AcquireV3LockActivityOutputs:
        return AcquireV3LockActivityOutputs(acquired=True, token="token")

    @activity.defn(name="create_external_data_job_model_activity")
    async def create_job(inputs: CreateExternalDataJobModelActivityInputs) -> CreateExternalDataJobModelActivityOutputs:
        return CreateExternalDataJobModelActivityOutputs(
            job_id=_JOB_ID,
            incremental_or_append=False,
            source_type="Postgres",
            schema_name="orders",
            repartition_needed=False,
            billing_limit_checked=True,
            source_templates_needed=False,
            import_handoffs_are_free=handoffs_are_free,
        )

    @activity.defn(name="import_data_activity_sync")
    async def import_data(inputs: ImportDataActivityInputs) -> PipelineResult:
        import_inputs.append(inputs)
        attempt = activity.info().attempt
        import_attempts.append(attempt)
        step = script[len(import_inputs) - 1] if len(import_inputs) <= len(script) else script[-1]
        if step == HANDOFF:
            return PipelineResult(should_trigger_cdp_producer=False, handed_off=True, handoff_attempts_used=attempt)
        if step == OLD_WORKER_HANDOFF:
            raise WorkerShuttingDownError("1", "import_data_activity_sync", _TASK_QUEUE, attempt, "wf", "wt")
        if step == FAIL:
            raise RuntimeError("source went away")
        return PipelineResult(should_trigger_cdp_producer=False, consumer_manages_job_status=True)

    @activity.defn(name="update_external_data_job_model")
    async def update_job(inputs: UpdateExternalDataJobStatusInputs) -> None:
        updates.append(inputs)

    @activity.defn(name="trigger_schedule_buffer_one_activity")
    async def trigger_buffer_one(schedule_id: str) -> None:
        buffer_one.append(schedule_id)

    return [acquire_lock, create_job, import_data, update_job, trigger_buffer_one]


def _patch_ids(history: WorkflowHistory) -> set[str]:
    patch_ids = set()
    for event in history.to_json_dict()["events"]:
        marker = event.get("markerRecordedEventAttributes")
        if marker and marker["markerName"] == "core_patch":
            payload = marker["details"]["patch-data"]["payloads"][0]["data"]
            patch_ids.add(json.loads(base64.b64decode(payload))["id"])
    return patch_ids


async def _run_workflow(script: list[str], *, handoffs_are_free: bool = True) -> _WorkflowRun:
    import_inputs: list[ImportDataActivityInputs] = []
    import_attempts: list[int] = []
    updates: list[UpdateExternalDataJobStatusInputs] = []
    buffer_one: list[str] = []
    failed = False

    with (
        mock.patch.object(workflow_module.workflow, "start_child_workflow", new_callable=mock.AsyncMock),
        mock.patch.object(workflow_module, "get_data_import_finished_metric"),
        mock.patch.object(workflow_module, "get_import_handoffs_per_run_metric") as handoffs_metric,
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=_TASK_QUEUE,
                workflows=[ExternalDataJobWorkflow],
                activities=_activities(
                    script,
                    handoffs_are_free=handoffs_are_free,
                    import_inputs=import_inputs,
                    import_attempts=import_attempts,
                    updates=updates,
                    buffer_one=buffer_one,
                ),
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=10),
            ):
                handle = await env.client.start_workflow(
                    ExternalDataJobWorkflow.run,
                    ExternalDataWorkflowInputs(
                        team_id=1,
                        external_data_source_id=uuid.uuid4(),
                        external_data_schema_id=uuid.uuid4(),
                        billable=False,
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=workflow_module.dt.timedelta(hours=1),
                )
                try:
                    await handle.result()
                except WorkflowFailureError:
                    failed = True
                history = await handle.fetch_history()

        handoffs_recorded = [call.args[0] for call in handoffs_metric.return_value.record.call_args_list]
        assert all(call.args == ("Postgres",) for call in handoffs_metric.call_args_list)

    return _WorkflowRun(
        import_inputs=import_inputs,
        import_attempts=import_attempts,
        updates=updates,
        buffer_one_triggers=len(buffer_one),
        handoffs_recorded=handoffs_recorded,
        history=history,
        failed=failed,
    )


@pytest.mark.asyncio
async def test_handoffs_do_not_use_the_failure_budget():
    # A full refresh gets 3 attempts. Five hand-offs would end the run if each one used an attempt.
    run = await _run_workflow([HANDOFF] * 5 + [SUCCEED])

    assert not run.failed
    assert [inputs.handoffs_are_free for inputs in run.import_inputs] == [True] * 6
    assert [inputs.handoff_count for inputs in run.import_inputs] == [0, 1, 2, 3, 4, 5]
    # Each execution continues the attempt numbers, so no two attempts share a run id.
    assert [inputs.prior_attempts for inputs in run.import_inputs] == [0, 1, 2, 3, 4, 5]
    assert run.buffer_one_triggers == 0
    assert run.handoffs_recorded == [5]
    # The loader owns the status of a run with batches, so the workflow writes none.
    assert run.updates == []


@pytest.mark.asyncio
async def test_failures_keep_one_budget_across_handoffs():
    # Attempt 1 fails and attempt 2 hands off, which leaves 2 of the 3 attempts for failures.
    run = await _run_workflow([FAIL, HANDOFF, FAIL, FAIL, SUCCEED])

    assert run.failed
    assert run.import_attempts == [1, 2, 1, 2]
    assert [inputs.prior_attempts for inputs in run.import_inputs] == [0, 0, 2, 2]
    assert [update.status for update in run.updates] == [ExternalDataJob.Status.FAILED]
    assert run.updates[0].latest_error != WORKER_RESTART_ERROR_MESSAGE
    assert run.buffer_one_triggers == 0


@pytest.mark.asyncio
async def test_the_handoff_loop_stops_at_its_bound():
    with mock.patch.object(workflow_module, "MAX_IMPORT_HANDOFFS", 3):
        run = await _run_workflow([HANDOFF])

    assert not run.failed
    assert len(run.import_inputs) == 3
    # The same outcome a run had when worker restarts used up its retries: failed with the
    # restart message, and the schedule is asked to run the schema once more.
    assert [(update.status, update.latest_error) for update in run.updates] == [
        (ExternalDataJob.Status.FAILED, WORKER_RESTART_ERROR_MESSAGE)
    ]
    assert run.buffer_one_triggers == 1
    assert run.handoffs_recorded == [3]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handoffs_are_free,script,expected_attempts,expected_buffer_one",
    [
        # The job-creation activity said hand-offs are not free: one execution, and Temporal's
        # retries end the run as before.
        pytest.param(False, [OLD_WORKER_HANDOFF], [1, 2, 3], 1, id="flag_off_keeps_the_retry_path"),
        # A worker without the hand-off result raises instead. The retry still works inside the loop.
        pytest.param(True, [OLD_WORKER_HANDOFF, HANDOFF, SUCCEED], [1, 2, 1], 0, id="old_worker_inside_the_loop"),
    ],
)
async def test_a_raised_handoff_still_goes_through_temporal_retries(
    handoffs_are_free: bool, script: list[str], expected_attempts: list[int], expected_buffer_one: int
):
    run = await _run_workflow(script, handoffs_are_free=handoffs_are_free)

    assert run.import_attempts == expected_attempts
    assert [inputs.handoffs_are_free for inputs in run.import_inputs] == [handoffs_are_free] * len(expected_attempts)
    assert run.buffer_one_triggers == expected_buffer_one
    assert run.handoffs_recorded == ([1] if handoffs_are_free else [])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handoffs_are_free,script",
    [
        # Histories recorded before the loop have one import execution and no patch marker. The
        # recorded histories next to this file cover a run that succeeds; these two cover the
        # hand-off outcomes, which no recorded history has.
        pytest.param(False, [OLD_WORKER_HANDOFF], id="pre_loop_history_with_retries_exhausted"),
        pytest.param(False, [OLD_WORKER_HANDOFF, SUCCEED], id="pre_loop_history_with_a_retried_handoff"),
        pytest.param(True, [HANDOFF, HANDOFF, SUCCEED], id="loop_history"),
        pytest.param(True, [HANDOFF], id="loop_history_at_the_bound"),
    ],
)
async def test_histories_replay_on_the_branch_they_recorded(handoffs_are_free: bool, script: list[str]):
    with mock.patch.object(workflow_module, "MAX_IMPORT_HANDOFFS", 3):
        run = await _run_workflow(script, handoffs_are_free=handoffs_are_free)

        assert (workflow_module.FREE_IMPORT_HANDOFFS_PATCH_ID in _patch_ids(run.history)) is handoffs_are_free

        with (
            mock.patch.object(workflow_module, "get_data_import_finished_metric"),
            mock.patch.object(workflow_module, "get_import_handoffs_per_run_metric"),
        ):
            await Replayer(
                workflows=[ExternalDataJobWorkflow],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ).replay_workflow(run.history)
