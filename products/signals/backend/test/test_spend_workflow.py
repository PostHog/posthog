import asyncio
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, patch

from django.test import override_settings

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from products.signals.backend.spend import SignalSpendUpdate, schedule_signal_spend_update
from products.signals.backend.temporal.spend import UpdateSignalSpendWorkflow


@pytest.mark.asyncio
async def test_spend_updates_retry_and_serialize_updates_arriving_during_and_after_a_write() -> None:
    queue = f"spend-test-{uuid4()}"
    driver = str(uuid4())
    write_started, release_write = asyncio.Event(), asyncio.Event()
    latest_spend = 1
    stored: list[int] = []
    attempts = 0

    @activity.defn(name="update_signal_spend_activity")
    async def write_metadata(input: SignalSpendUpdate) -> None:
        nonlocal attempts
        assert input == SignalSpendUpdate(team_id=1, signal_id=driver)
        attempts += 1
        if attempts == 1:
            raise ApplicationError("ClickHouse row not visible yet", type="SignalSpendNotVisible")
        spend = latest_spend
        if attempts == 2:
            write_started.set()
            await release_write.wait()
        stored.append(spend)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client, task_queue=queue, workflows=[UpdateSignalSpendWorkflow], activities=[write_metadata]
        ):
            with (
                override_settings(VIDEO_EXPORT_TASK_QUEUE=queue),
                patch("posthog.temporal.common.client.async_connect", new=AsyncMock(return_value=env.client)),
            ):
                await schedule_signal_spend_update(team_id=1, signal_id=driver)
                await asyncio.wait_for(write_started.wait(), timeout=20)
                latest_spend = 2
                await schedule_signal_spend_update(team_id=1, signal_id=driver)
                release_write.set()
                handle = env.client.get_workflow_handle(f"signal-spend-1-{driver}")
                await asyncio.wait_for(handle.result(), timeout=20)
                assert stored == [1, 2]

                latest_spend = 3
                await schedule_signal_spend_update(team_id=1, signal_id=driver)
                await asyncio.wait_for(handle.result(), timeout=20)
                assert stored == [1, 2, 3]
