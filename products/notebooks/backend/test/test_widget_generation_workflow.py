import uuid
from datetime import timedelta

import pytest
from unittest.mock import MagicMock, patch

from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.notebooks.backend.temporal.client import start_widget_generation_workflow
from products.notebooks.backend.temporal.widget_generation import (
    GENERATION_CAPACITY_ERROR_TYPE,
    NotebookWidgetGenerationWorkflow,
    WidgetGenerationInput,
)


def test_generation_workflow_start_has_an_execution_timeout() -> None:
    temporal = MagicMock()
    job_id = str(uuid.uuid4())

    with (
        patch("products.notebooks.backend.temporal.client.sync_connect", return_value=temporal),
        patch("products.notebooks.backend.temporal.client._start_workflow") as start,
    ):
        start_widget_generation_workflow(job_id, 123)

    start.assert_called_once_with(
        temporal,
        "notebook-widget-generate",
        f"notebook-widget-generate-{job_id}",
        WidgetGenerationInput(job_id=job_id, team_id=123),
        execution_timeout=timedelta(minutes=30),
    )


@pytest.mark.asyncio
async def test_generation_activity_failure_marks_the_job_failed() -> None:
    attempts = 0
    failed_inputs: list[WidgetGenerationInput] = []

    @activity.defn(name="notebook-widget-generate")
    async def fail_generation(inputs: WidgetGenerationInput) -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("worker stopped")

    @activity.defn(name="notebook-widget-generate-mark-failed")
    async def mark_failed(inputs: WidgetGenerationInput) -> None:
        failed_inputs.append(inputs)

    job_id = str(uuid.uuid4())
    inputs = WidgetGenerationInput(job_id=job_id, team_id=123)
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
                    inputs,
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

    assert attempts == 1
    assert failed_inputs == [inputs]


@pytest.mark.asyncio
async def test_generation_capacity_retries_without_failing_the_job() -> None:
    attempts = 0
    failed_inputs: list[WidgetGenerationInput] = []

    @activity.defn(name="notebook-widget-generate")
    async def generate(inputs: WidgetGenerationInput) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ApplicationError("capacity full", type=GENERATION_CAPACITY_ERROR_TYPE, non_retryable=True)

    @activity.defn(name="notebook-widget-generate-mark-failed")
    async def mark_failed(inputs: WidgetGenerationInput) -> None:
        failed_inputs.append(inputs)

    inputs = WidgetGenerationInput(job_id=str(uuid.uuid4()), team_id=123)
    task_queue = str(uuid.uuid4())

    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[NotebookWidgetGenerationWorkflow],
            activities=[generate, mark_failed],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await environment.client.execute_workflow(
                NotebookWidgetGenerationWorkflow.run,
                inputs,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert attempts == 2
    assert failed_inputs == []
