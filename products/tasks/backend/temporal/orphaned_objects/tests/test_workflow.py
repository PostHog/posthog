import os
import uuid
import dataclasses
from collections.abc import AsyncIterator

import pytest
from unittest.mock import patch

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.logic.services.orphaned_objects import OrphanedObjectsTotals
from products.tasks.backend.logic.services.orphaned_objects_runs import (
    TOTALS_MEMO_KEY,
    WORKFLOW_NAME,
    OrphanedObjectsInput,
)
from products.tasks.backend.temporal.orphaned_objects import workflow
from products.tasks.backend.temporal.orphaned_objects.workflow import DeleteOrphanedTaskObjectsWorkflow

TOTALS = OrphanedObjectsTotals(prefixes=2, objects=5, size_bytes=50, failed_objects=1)


@pytest.fixture
async def env() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping(
        test_server_existing_path=os.environ.get("TEMPORAL_TEST_SERVER_PATH")
    ) as environment:
        yield environment


@activity.defn(name="delete_orphaned_task_objects")
async def fake_delete_orphaned_task_objects(input: OrphanedObjectsInput) -> OrphanedObjectsTotals:
    return TOTALS


@pytest.mark.asyncio
async def test_a_finished_run_records_its_totals_in_the_memo(env: WorkflowEnvironment) -> None:
    task_queue = f"orphaned-objects-{uuid.uuid4()}"
    async with Worker(
        env.client,
        task_queue=task_queue,
        workflows=[DeleteOrphanedTaskObjectsWorkflow],
        activities=[fake_delete_orphaned_task_objects],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        handle = await env.client.start_workflow(
            WORKFLOW_NAME,
            OrphanedObjectsInput(kinds=["logs"], max_prefixes=2, execute=True, requested_by="staff@example.com"),
            id=f"{WORKFLOW_NAME}-{uuid.uuid4()}",
            task_queue=task_queue,
        )
        await handle.result()
        memo = await (await handle.describe()).memo()

    assert memo[TOTALS_MEMO_KEY] == dataclasses.asdict(TOTALS)


def test_heartbeats_skip_unchanged_totals_but_never_a_finished_prefix() -> None:
    first = OrphanedObjectsTotals(prefixes=1)
    second = OrphanedObjectsTotals(prefixes=2)
    with (
        patch.object(workflow, "heartbeat_from_thread") as heartbeat,
        patch.object(workflow.time, "monotonic", return_value=100.0),
    ):
        throttled = workflow.ThrottledHeartbeat()
        for totals in (first, first, second, second):
            throttled(totals)

    assert [call.args[0]["prefixes"] for call in heartbeat.call_args_list] == [1, 2]
