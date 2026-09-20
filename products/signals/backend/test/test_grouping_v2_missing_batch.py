import json
import uuid
import asyncio
from dataclasses import asdict

import pytest
from unittest.mock import patch

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.signals.backend.temporal.grouping_v2 import TeamSignalGroupingV2Workflow, read_signals_from_s3_activity
from products.signals.backend.temporal.types import EmitSignalInputs, TeamSignalGroupingV2Input

TASK_QUEUE = "test-grouping-v2-queue"
GROUPING_V2_MODULE = "products.signals.backend.temporal.grouping_v2"

MISSING_KEY = "signals/signal_batches/gone"
PRESENT_KEY = "signals/signal_batches/here"


def _signal(team_id: int) -> EmitSignalInputs:
    return EmitSignalInputs(
        team_id=team_id,
        source_product="error_tracking",
        source_type="issue",
        source_id=str(uuid.uuid4()),
        description="something happened",
    )


class TestGroupingV2MissingBatch:
    @pytest.mark.asyncio
    async def test_workflow_processes_the_batches_behind_a_missing_one(self):
        kept = _signal(1)
        processed: list[list[EmitSignalInputs]] = []
        done = asyncio.Event()

        def fake_storage_read(object_key: str, *args, **kwargs) -> str | None:
            return None if object_key == MISSING_KEY else json.dumps([asdict(kept)])

        async def fake_process(signals, cached_type_examples=None):
            processed.append(list(signals))
            done.set()
            return 0, None

        with (
            patch(f"{GROUPING_V2_MODULE}.object_storage.read", side_effect=fake_storage_read),
            patch(f"{GROUPING_V2_MODULE}._process_signal_batch", side_effect=fake_process),
        ):
            async with await WorkflowEnvironment.start_time_skipping() as env:
                async with Worker(
                    env.client,
                    task_queue=TASK_QUEUE,
                    workflows=[TeamSignalGroupingV2Workflow],
                    activities=[read_signals_from_s3_activity],
                    workflow_runner=UnsandboxedWorkflowRunner(),
                ):
                    handle = await env.client.start_workflow(
                        TeamSignalGroupingV2Workflow.run,
                        TeamSignalGroupingV2Input(team_id=1),
                        id=f"grouping-v2-{uuid.uuid4()}",
                        task_queue=TASK_QUEUE,
                    )
                    await handle.signal(TeamSignalGroupingV2Workflow.submit_batch, MISSING_KEY)
                    await handle.signal(TeamSignalGroupingV2Workflow.submit_batch, PRESENT_KEY)
                    await asyncio.wait_for(done.wait(), timeout=60)
                    assert (await handle.describe()).status.name == "RUNNING"
                    await handle.terminate()

        assert processed == [[kept]]
