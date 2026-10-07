import os
import uuid

import pytest

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.temporal.delegate_task import DelegateTaskInput, DelegateTaskWorkflow, FailDelegatedRunInput

TASK_QUEUE = "delegate-task-test"


def _environment():
    return WorkflowEnvironment.start_time_skipping(
        test_server_existing_path=os.environ.get("TEMPORAL_TEST_SERVER_PATH")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("brief_fails", [False, True])
async def test_a_failed_brief_fails_the_run_instead_of_dispatching(brief_fails: bool) -> None:
    calls: list[str] = []

    @activity.defn(name="brief_task_run")
    async def brief_task_run(input: DelegateTaskInput) -> None:
        calls.append("brief")
        if brief_fails:
            raise ApplicationError("brief has no prompt", type="BriefError", non_retryable=True)

    @activity.defn(name="dispatch_briefed_run")
    async def dispatch_briefed_run(input: DelegateTaskInput) -> None:
        calls.append("dispatch")

    @activity.defn(name="fail_delegated_run")
    async def fail_delegated_run(input: FailDelegatedRunInput) -> None:
        calls.append(f"fail:{input.error_message}")

    run_id = str(uuid.uuid4())
    async with await _environment() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[DelegateTaskWorkflow],
            activities=[brief_task_run, dispatch_briefed_run, fail_delegated_run],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                DelegateTaskWorkflow.run,
                DelegateTaskInput(run_id=run_id),
                id=f"delegate-task-{run_id}",
                task_queue=TASK_QUEUE,
            )

    if brief_fails:
        assert calls == ["brief", "fail:Could not brief the delegated run: brief has no prompt"]
    else:
        assert calls == ["brief", "dispatch"]
