import asyncio
import logging
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, Mock, patch

from django.test import override_settings

from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.logic.services.gateway_usage import (
    _gateway_usage_client,
    _schedule_gateway_usage,
    schedule_gateway_usage,
)
from products.tasks.backend.temporal.gateway_usage import GatewayUsageInput, TaskRunGatewayUsageWorkflow


@pytest.mark.parametrize("failed_connection", [False, True])
async def test_scheduling_reuses_connection_after_success_and_retries_failure(failed_connection: bool) -> None:
    client = Mock(start_workflow=AsyncMock())
    _gateway_usage_client.cache_clear()
    with patch("posthog.temporal.common.client.async_connect", new_callable=AsyncMock) as connect:
        connect.side_effect = [RuntimeError("unavailable"), client] if failed_connection else None
        connect.return_value = client
        if failed_connection:
            with pytest.raises(RuntimeError, match="unavailable"):
                await _schedule_gateway_usage(run_id=uuid4(), team_id=7)
        await asyncio.gather(*(_schedule_gateway_usage(run_id=uuid4(), team_id=7) for _ in range(2)))
        await sync_to_async(schedule_gateway_usage)(run_id=uuid4(), team_id=7)
        assert connect.await_count == (2 if failed_connection else 1)
        assert client.start_workflow.await_count == 3
    _gateway_usage_client.cache_clear()


def test_scheduling_reconnects_when_event_loop_changes() -> None:
    async def connect():
        loop = asyncio.get_running_loop()

        async def start(*args, **kwargs):
            assert asyncio.get_running_loop() is loop

        return Mock(start_workflow=AsyncMock(side_effect=start))

    with patch("posthog.temporal.common.client.async_connect", side_effect=connect) as connection:
        for _ in range(2):
            asyncio.run(_schedule_gateway_usage(run_id=uuid4(), team_id=7))
        assert connection.await_count == 2
    _gateway_usage_client.cache_clear()


async def test_reconciliation_drains_retries_and_accepts_late_callbacks() -> None:
    run_id = uuid4()
    pending = list(range(23))
    attempts = 0
    signal_on_empty = True

    @activity.defn(name="reconcile_gateway_usage")
    async def reconcile(input: GatewayUsageInput) -> int:
        nonlocal attempts, signal_on_empty
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary outage")
        del pending[:20]
        remaining = len(pending)
        if remaining == 0 and signal_on_empty:
            signal_on_empty = False
            pending.append(24)
            await _schedule_gateway_usage(run_id=run_id, team_id=7)
        return remaining

    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="gateway-usage-test",
            workflows=[TaskRunGatewayUsageWorkflow],
            activities=[reconcile],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ),
    ):
        handles = []
        start_workflow = env.client.start_workflow

        async def capture_workflow(*args, **kwargs):
            handle = await start_workflow(*args, **kwargs)
            handles.append(handle)
            return handle

        with (
            patch.object(env.client, "start_workflow", side_effect=capture_workflow),
            override_settings(TASKS_TASK_QUEUE="gateway-usage-test"),
            patch(
                "posthog.temporal.common.client.async_connect",
                new=AsyncMock(return_value=env.client),
            ),
        ):
            await _schedule_gateway_usage(run_id=run_id, team_id=7)
            handle = handles[0]
            await asyncio.wait_for(handle.result(), timeout=30)
            assert pending == []
            assert attempts == 4

            pending.append(25)
            await _schedule_gateway_usage(run_id=run_id, team_id=7)
            await asyncio.wait_for(handles[-1].result(), timeout=30)
            assert pending == []
            assert attempts == 5


async def test_reconciliation_drains_settled_backlog_without_backoff() -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        pending = 100
        call_times: list[datetime] = []

        @activity.defn(name="reconcile_gateway_usage")
        async def reconcile(input: GatewayUsageInput) -> int:
            nonlocal pending
            call_times.append(await env.get_current_time())
            pending = max(pending - 20, 0)
            return pending

        async with Worker(
            env.client,
            task_queue="gateway-usage-test",
            workflows=[TaskRunGatewayUsageWorkflow],
            activities=[reconcile],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            run_id = uuid4()
            await env.client.execute_workflow(
                TaskRunGatewayUsageWorkflow.run,
                GatewayUsageInput(run_id=str(run_id), team_id=7),
                id=f"backlog-{run_id}",
                task_queue="gateway-usage-test",
                execution_timeout=timedelta(hours=1),
            )
        assert pending == 0
        assert len(call_times) == 5
        assert call_times[-1] - call_times[0] < timedelta(minutes=1)


@pytest.mark.parametrize("activity_failure", [False, True])
async def test_reconciliation_expires_with_unresolved_usage(
    activity_failure: bool, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="temporalio.workflow")

    @activity.defn(name="reconcile_gateway_usage")
    async def reconcile(input: GatewayUsageInput) -> int:
        if activity_failure:
            raise RuntimeError("persistent outage")
        return 1

    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="gateway-usage-test",
            workflows=[TaskRunGatewayUsageWorkflow],
            activities=[reconcile],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ),
    ):
        run_id = uuid4()
        await env.client.execute_workflow(
            TaskRunGatewayUsageWorkflow.run,
            GatewayUsageInput(
                run_id=str(run_id), team_id=7, retry_until=await env.get_current_time() + timedelta(minutes=1)
            ),
            id=f"exhausted-{run_id}",
            task_queue="gateway-usage-test",
            execution_timeout=timedelta(minutes=5),
        )
        assert "task_gateway_usage.retries_exhausted" in caplog.text


async def test_callback_extends_deadline_during_activity_retries() -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        run_id = uuid4()
        workflow_id = f"extended-{run_id}"
        original_deadline = await env.get_current_time() + timedelta(minutes=1)
        signaled = False
        settled = False

        @activity.defn(name="reconcile_gateway_usage")
        async def reconcile(input: GatewayUsageInput) -> int:
            nonlocal signaled, settled
            if not signaled:
                signaled = True
                await env.client.get_workflow_handle(workflow_id).signal(TaskRunGatewayUsageWorkflow.requests_available)
            if await env.get_current_time() < original_deadline:
                raise RuntimeError("outage until original deadline")
            settled = True
            return 0

        async with Worker(
            env.client,
            task_queue="gateway-usage-test",
            workflows=[TaskRunGatewayUsageWorkflow],
            activities=[reconcile],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                TaskRunGatewayUsageWorkflow.run,
                GatewayUsageInput(run_id=str(run_id), team_id=7, retry_until=original_deadline),
                id=workflow_id,
                task_queue="gateway-usage-test",
                execution_timeout=timedelta(minutes=5),
            )
        assert settled
