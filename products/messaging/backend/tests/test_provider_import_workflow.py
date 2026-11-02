import uuid
import logging
from datetime import timedelta

import pytest

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.messaging.backend.temporal.inputs import (
    ProviderImportRunInputs,
    ProviderImportStepInputs,
    ProviderImportWorkflowInputs,
)
from products.messaging.backend.temporal.workflow import ProviderImportWorkflow


@pytest.mark.asyncio
async def test_a_failed_step_does_not_stop_later_steps_or_the_finish(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    attempted_steps: list[str] = []
    finished_runs: list[str] = []

    @activity.defn(name="messaging-provider-import.run_step")
    async def run_step(inputs: ProviderImportStepInputs) -> None:
        attempted_steps.append(inputs.step)
        if inputs.step == "categories":
            raise ApplicationError("The key was deleted", type="ImportCredentialsMissing")

    @activity.defn(name="messaging-provider-import.finish_run")
    async def finish_run(inputs: ProviderImportRunInputs) -> None:
        finished_runs.append(inputs.run_id)

    run_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="provider-import-test",
            workflows=[ProviderImportWorkflow],
            activities=[run_step, finish_run],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                ProviderImportWorkflow.run,
                ProviderImportWorkflowInputs(team_id=1, run_id=run_id, steps=["categories", "suppressions"]),
                id=f"provider-import-test-{run_id}",
                task_queue="provider-import-test",
                execution_timeout=timedelta(minutes=5),
            )

    assert attempted_steps == ["categories", "suppressions"]
    assert finished_runs == [run_id]
