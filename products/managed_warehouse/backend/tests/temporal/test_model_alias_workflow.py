import asyncio
import datetime as dt
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, patch

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.managed_warehouse.backend.model_alias_dispatch import request_model_alias_reconciliation
from products.managed_warehouse.backend.temporal.model_alias_workflow import (
    ModelAliasBatch,
    ModelAliasInputs,
    ReconcileModelAliasesWorkflow,
)
from products.managed_warehouse.backend.trino_model_aliases import ModelAliasReconciliation


@pytest.mark.asyncio
async def test_dispatch_coalesces_builds_into_one_team_workflow() -> None:
    client = AsyncMock()
    with patch("products.managed_warehouse.backend.model_alias_dispatch.async_connect", return_value=client):
        await request_model_alias_reconciliation(42, "12345678-1234-5678-1234-567812345678")
    args = client.start_workflow.call_args
    assert args.args == ("managed-warehouse.reconcile-model-aliases", {"team_id": 42})
    assert args.kwargs["id"] == "managed-warehouse-model-aliases/42"
    assert args.kwargs["start_signal"] == "refresh"
    assert args.kwargs["start_signal_args"] == ["12345678-1234-5678-1234-567812345678"]


@pytest.mark.asyncio
@pytest.mark.parametrize("first_pass_fails", [True, False])
async def test_refresh_during_failed_or_empty_pass_is_processed_afterwards(first_pass_fails: bool) -> None:
    entered: asyncio.Queue[int] = asyncio.Queue()
    releases = [asyncio.Event(), asyncio.Event(), asyncio.Event()]
    calls = 0

    @activity.defn(name="reconcile_trino_model_aliases_activity")
    async def reconcile(inputs: ModelAliasBatch) -> ModelAliasReconciliation:
        nonlocal calls
        attempt = calls
        calls += 1
        await entered.put(attempt)
        await releases[attempt].wait()
        if attempt == 0 and first_pass_fails:
            raise ApplicationError("Catalog temporarily unavailable", non_retryable=True)
        return ModelAliasReconciliation(published=1, active=attempt == 1)

    async with await WorkflowEnvironment.start_time_skipping() as environment:
        queue = f"model-alias-test-{uuid4()}"
        async with Worker(
            environment.client,
            task_queue=queue,
            workflows=[ReconcileModelAliasesWorkflow],
            activities=[reconcile],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await environment.client.start_workflow(
                ReconcileModelAliasesWorkflow.run,
                ModelAliasInputs(team_id=42),
                id=f"model-alias-{uuid4()}",
                task_queue=queue,
                execution_timeout=dt.timedelta(minutes=10),
            )
            result_task = asyncio.create_task(handle.result())
            try:
                assert await asyncio.wait_for(entered.get(), timeout=10) == 0
                await handle.signal(ReconcileModelAliasesWorkflow.refresh)
                assert calls == 1
                releases[0].set()
                assert await asyncio.wait_for(entered.get(), timeout=10) == 1
                assert bool((await handle.query(ReconcileModelAliasesWorkflow.status)).errors) == first_pass_fails
                await handle.signal(ReconcileModelAliasesWorkflow.refresh)
                releases[1].set()
                assert await asyncio.wait_for(entered.get(), timeout=10) == 2
                assert await handle.query(ReconcileModelAliasesWorkflow.status) == ModelAliasReconciliation(published=1)
                releases[2].set()
                await asyncio.wait_for(result_task, timeout=10)
            finally:
                for release in releases:
                    release.set()
                if not result_task.done():
                    await handle.cancel()
                    await asyncio.gather(result_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_batches_large_refresh_and_stops_when_team_becomes_inactive() -> None:
    batches: list[tuple[str, ...] | None] = []

    @activity.defn(name="reconcile_trino_model_aliases_activity")
    async def reconcile(inputs: ModelAliasBatch) -> ModelAliasReconciliation:
        batches.append(inputs.saved_query_ids)
        return ModelAliasReconciliation(active=len(batches) < 3)

    ids = tuple(str(uuid4()) for _ in range(201))
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        queue = f"model-alias-test-{uuid4()}"
        async with Worker(
            environment.client,
            task_queue=queue,
            workflows=[ReconcileModelAliasesWorkflow],
            activities=[reconcile],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await environment.client.execute_workflow(
                ReconcileModelAliasesWorkflow.run,
                ModelAliasInputs(team_id=42, pending_ids=ids),
                id=f"model-alias-{uuid4()}",
                task_queue=queue,
                execution_timeout=dt.timedelta(minutes=10),
            )
    assert [len(batch or ()) for batch in batches] == [100, 100, 1]
    assert sorted(item for batch in batches for item in batch or ()) == sorted(ids)
