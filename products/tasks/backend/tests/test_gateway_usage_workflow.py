import asyncio
import logging
from datetime import timedelta
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, patch

from django.test import override_settings

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.logic.services.gateway_usage import _schedule_gateway_usage
from products.tasks.backend.temporal.gateway_usage import GatewayUsageInput, TaskRunGatewayUsageWorkflow


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
