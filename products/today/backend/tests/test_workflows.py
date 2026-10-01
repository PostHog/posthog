import uuid
from collections.abc import AsyncIterator

import pytest

from django.conf import settings

import pytest_asyncio
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.today.backend.temporal.inputs import GENERATE_WORKFLOW_NAME, GenerateBriefingInputs, MarkFailedInputs
from products.today.backend.temporal.workflows import GenerateTodayBriefingWorkflow


@pytest_asyncio.fixture(scope="module")
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest.mark.asyncio
async def test_an_agent_failure_marks_the_briefing_failed_once(environment: WorkflowEnvironment) -> None:
    attempts = 0
    marked_failed: list[MarkFailedInputs] = []

    @activity.defn(name="run_agent_activity")
    async def run_agent(inputs: GenerateBriefingInputs) -> None:
        nonlocal attempts
        attempts += 1
        raise ApplicationError("The agent finished without storing the briefing.")

    @activity.defn(name="mark_failed_activity")
    async def mark_failed(inputs: MarkFailedInputs) -> None:
        marked_failed.append(inputs)

    async with Worker(
        environment.client,
        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        workflows=[GenerateTodayBriefingWorkflow],
        activities=[run_agent, mark_failed],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        await environment.client.execute_workflow(
            GENERATE_WORKFLOW_NAME,
            GenerateBriefingInputs(team_id=1, briefing_id="b-1"),
            id=str(uuid.uuid4()),
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        )

    # One attempt: a retry would start a second sandbox for the same briefing.
    assert attempts == 1
    assert [failed.error for failed in marked_failed] == ["The agent finished without storing the briefing."]
