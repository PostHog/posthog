from datetime import datetime, timedelta

import pytest

from modal.exception import TimeoutError as ModalTimeoutError
from pytest_mock import MockerFixture
from temporalio import activity, workflow
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox
from products.tasks.backend.temporal.process_task.activities.cleanup_sandbox import (
    CleanupSandboxInput,
    cleanup_sandbox_now,
)
from products.tasks.backend.temporal.process_task.expire_retained_sandbox import ExpireRetainedSandboxWorkflow
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow


@workflow.defn
class RetainingParentWorkflow:
    @workflow.run
    async def run(self) -> None:
        await ProcessTaskWorkflow()._cleanup_sandbox("sandbox-123", retain_sandbox=True)
        if workflow.info().attempt == 1:
            raise ApplicationError("status persistence failed")


@pytest.mark.asyncio
async def test_retained_cleanup_outlives_parent_and_retries_after_deadline(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger="temporalio.workflow")
    caplog.set_level("INFO", logger="temporalio.activity")
    calls: list[tuple[CleanupSandboxInput, datetime]] = []
    handle = mocker.Mock(object_id="sandbox-123")
    handle.name = "retained-sandbox"
    mocker.patch.object(ModalSandbox, "_get_app_for_config")
    lookup = mocker.patch(
        "products.tasks.backend.logic.services.modal_sandbox.modal.Sandbox.from_id",
        side_effect=[ModalTimeoutError("lookup timed out"), handle],
    )
    module = "products.tasks.backend.temporal.process_task.activities.cleanup_sandbox"
    mocker.patch(f"{module}.get_sandbox_class_for_sandbox_id", return_value=ModalSandbox)
    mocker.patch(f"{module}.close_sandbox_session")
    mocker.patch(f"{module}.measure_sandbox_cpu_usage", return_value=(None, None))
    mocker.patch(f"{module}.measure_sandbox_billed_cpu_usage", return_value=None)

    @activity.defn(name="cleanup_sandbox")
    async def cleanup(input: CleanupSandboxInput) -> None:
        calls.append((input, activity.info().current_attempt_scheduled_time))
        if not input.retain_sandbox:
            cleanup_sandbox_now(input)

    @activity.defn(name="retain_sandbox_for_recovery")
    async def retain(input: CleanupSandboxInput) -> None:
        calls.append((input, activity.info().current_attempt_scheduled_time))
        if len(calls) == 1:
            raise ApplicationError("upload unavailable", non_retryable=True)

    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="test-retained-sandbox",
            workflows=[RetainingParentWorkflow, ExpireRetainedSandboxWorkflow],
            activities=[cleanup, retain],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ),
    ):
        started_at = await env.get_current_time()
        with env.auto_time_skipping_disabled():
            await env.client.execute_workflow(
                RetainingParentWorkflow.run,
                id="retaining-parent",
                task_queue="test-retained-sandbox",
                execution_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=2, initial_interval=timedelta(milliseconds=1)),
            )
        assert len(calls) == 2
        retained = env.client.get_workflow_handle("expire-retained-sandbox-sandbox-123")
        assert (await retained.describe()).status == WorkflowExecutionStatus.RUNNING
        await retained.terminate()
        await env.sleep(timedelta(minutes=14))
        await env.client.execute_workflow(
            ExpireRetainedSandboxWorkflow.run,
            CleanupSandboxInput(sandbox_id="sandbox-123", recovery_deadline=calls[0][0].recovery_deadline),
            id="retry-cleanup",
            task_queue="test-retained-sandbox",
            execution_timeout=timedelta(minutes=3),
        )

    assert len(calls) == 4
    assert lookup.call_count == 2
    handle.terminate.assert_called_once_with()
    assert calls[0][0].retain_sandbox
    assert calls[0][0].recovery_deadline is not None
    assert timedelta(minutes=15) <= calls[2][1] - started_at < timedelta(minutes=16)
    assert calls[1][0].retain_sandbox
    for input, _ in calls[2:]:
        assert input.sandbox_id == "sandbox-123"
        assert not input.retain_sandbox
        assert input.raise_on_error
