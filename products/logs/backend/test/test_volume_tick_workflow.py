import uuid
from dataclasses import asdict
from datetime import datetime

import pytest

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.logs.backend.temporal.volume_tick.activities import VolumeTickInput, volume_tick_heartbeat_activity
from products.logs.backend.temporal.volume_tick.constants import WORKFLOW_NAME
from products.logs.backend.temporal.volume_tick.workflow import LogsVolumeTickWorkflow

TASK_QUEUE = "logs-volume-tick-test"


@pytest.mark.asyncio
async def test_schedule_shaped_invocation_runs_the_heartbeat() -> None:
    # Invoke by workflow name with an asdict payload — the exact contract the
    # Temporal schedule uses — so a rename or input-shape drift fails here.
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[LogsVolumeTickWorkflow],
            activities=[volume_tick_heartbeat_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WORKFLOW_NAME,
                asdict(VolumeTickInput()),
                id=f"test-volume-tick-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )

    assert datetime.fromisoformat(result["ticked_at"]).tzinfo is not None
