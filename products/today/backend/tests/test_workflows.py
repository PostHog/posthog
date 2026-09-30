import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest

from django.conf import settings

import pytest_asyncio
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.today.backend.facade.enums import ItemGroup, ItemReason, ItemSource
from products.today.backend.logic.candidates import Candidate
from products.today.backend.logic.sources import SOURCE_NAMES
from products.today.backend.temporal.inputs import (
    GENERATE_WORKFLOW_NAME,
    CollectSourceInputs,
    DraftInputs,
    GenerateBriefingInputs,
    MarkFailedInputs,
)
from products.today.backend.temporal.workflows import GenerateTodayBriefingWorkflow


@pytest_asyncio.fixture(scope="module")
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest.mark.asyncio
async def test_a_failing_source_loses_only_its_own_items(environment: WorkflowEnvironment) -> None:
    drafted: list[DraftInputs] = []
    marked_failed: list[MarkFailedInputs] = []
    github_attempts = 0

    @activity.defn(name="collect_source_activity")
    async def collect_source(inputs: CollectSourceInputs) -> list[dict[str, Any]]:
        nonlocal github_attempts
        if inputs.source == "github":
            github_attempts += 1
            raise ApplicationError("GitHub is down")
        return [
            Candidate(
                key=f"{inputs.source}:1",
                group=ItemGroup.OTHER,
                source=ItemSource.SUPPORT,
                reason=ItemReason.ASSIGNED_TICKET,
                title="Ticket #1042",
                url="/project/1/support/tickets/1",
                sort_key=(0.0,),
                facts={"unread_messages": 3},
            ).to_payload()
        ]

    @activity.defn(name="draft_activity")
    async def draft(inputs: DraftInputs) -> bool:
        drafted.append(inputs)
        return False

    @activity.defn(name="write_and_check_activity")
    async def write_and_check(inputs: GenerateBriefingInputs) -> None:
        raise AssertionError("an ineligible briefing is never written")

    @activity.defn(name="mark_failed_activity")
    async def mark_failed(inputs: MarkFailedInputs) -> None:
        marked_failed.append(inputs)

    async with Worker(
        environment.client,
        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        workflows=[GenerateTodayBriefingWorkflow],
        activities=[collect_source, draft, write_and_check, mark_failed],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        await environment.client.execute_workflow(
            GENERATE_WORKFLOW_NAME,
            GenerateBriefingInputs(team_id=1, briefing_id=str(uuid.uuid4())),
            id=str(uuid.uuid4()),
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        )

    assert marked_failed == []
    assert github_attempts == 2
    [draft_inputs] = drafted
    assert draft_inputs.failed_sources == ["github"]
    assert sorted(Candidate.from_payload(payload).key for payload in draft_inputs.candidates) == sorted(
        f"{source}:1" for source in SOURCE_NAMES if source != "github"
    )
