import asyncio
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, patch

from django.test import override_settings

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.signals.backend.spend import (
    SignalMetadataChange,
    SignalSpendPublication,
    SignalSpendSummary,
    SignalSpendUpdate,
    publish_signal_spend,
    submit_signal_metadata_updates,
)
from products.signals.backend.temporal.spend import UpdateSignalSpendWorkflow


@pytest.mark.asyncio
async def test_spend_updates_retry_and_serialize_updates_arriving_during_and_after_a_write() -> None:
    queue = f"spend-test-{uuid4()}"
    driver = str(uuid4())
    write_started, release_write = asyncio.Event(), asyncio.Event()
    latest_spend = 1
    stored: list[int] = []
    changes: list[SignalMetadataChange] = []
    attempts = 0

    @activity.defn(name="update_signal_spend_activity")
    async def write_metadata(input: SignalSpendUpdate) -> SignalSpendPublication:
        nonlocal attempts
        assert (input.team_id, input.signal_id) == (1, driver)
        attempts += 1
        if attempts == 1:
            raise ApplicationError("ClickHouse row not visible yet", type="SignalSpendNotVisible")
        spend = latest_spend
        if attempts == 2:
            write_started.set()
            await release_write.wait()
        stored.append(spend)
        changes.extend(input.changes)
        return SignalSpendPublication(
            signal=input, summary=SignalSpendSummary(total_spend=spend, failed_stages=[]), versions={}
        )

    confirmation_attempts = 0

    @activity.defn(name="confirm_signal_spend_activity")
    async def confirm_metadata(input: SignalSpendPublication) -> None:
        nonlocal confirmation_attempts
        confirmation_attempts += 1
        if confirmation_attempts == 1:
            raise ApplicationError("ClickHouse ingestion delayed", type="SignalSpendNotVisible")

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=queue,
            workflows=[UpdateSignalSpendWorkflow],
            activities=[write_metadata, confirm_metadata],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with (
                override_settings(VIDEO_EXPORT_TASK_QUEUE=queue),
                patch("posthog.temporal.common.client.async_connect", new=AsyncMock(return_value=env.client)),
            ):
                publication = asyncio.create_task(publish_signal_spend(team_id=1, signal_id=driver))
                await asyncio.wait_for(write_started.wait(), timeout=20)
                assert not publication.done()
                latest_spend = 2
                change = SignalMetadataChange(report_id="new-report", expected_report_id="old-report")
                await submit_signal_metadata_updates(team_id=1, signal_ids=[driver], change=change)
                handle = env.client.get_workflow_handle(f"signal-spend-1-{driver}")
                await handle.signal("refresh")
                release_write.set()
                await asyncio.wait_for(publication, timeout=20)
                assert stored == [1, 2]
                assert changes == [change]

                latest_spend = 3
                await publish_signal_spend(team_id=1, signal_id=driver)
                assert stored == [1, 2, 3]
                assert confirmation_attempts == 4
