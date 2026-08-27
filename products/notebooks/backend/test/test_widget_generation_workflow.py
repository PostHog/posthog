import uuid

import pytest

from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.notebooks.backend.temporal.widget_generation import NotebookWidgetGenerationWorkflow


@pytest.mark.asyncio
async def test_generation_activity_failure_marks_the_job_failed() -> None:
    attempts = 0
    failed_job_ids: list[str] = []

    @activity.defn(name="notebook-widget-generate")
    async def fail_generation(job_id: str) -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("worker stopped")

    @activity.defn(name="notebook-widget-generate-mark-failed")
    async def mark_failed(job_id: str) -> None:
        failed_job_ids.append(job_id)

    job_id = str(uuid.uuid4())
    task_queue = str(uuid.uuid4())

    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[NotebookWidgetGenerationWorkflow],
            activities=[fail_generation, mark_failed],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await environment.client.execute_workflow(
                    NotebookWidgetGenerationWorkflow.run,
                    job_id,
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

    assert attempts == 1
    assert failed_job_ids == [job_id]
