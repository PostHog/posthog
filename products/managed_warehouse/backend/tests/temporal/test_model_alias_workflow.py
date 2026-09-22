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
    ModelAliasInputs,
    ReconcileModelAliasesWorkflow,
)
from products.managed_warehouse.backend.trino_model_aliases import ModelAliasReconciliation


@pytest.mark.asyncio
async def test_dispatch_coalesces_builds_into_one_team_workflow() -> None:
    client = AsyncMock()
    with patch("products.managed_warehouse.backend.model_alias_dispatch.async_connect", return_value=client):
        await request_model_alias_reconciliation(42)
    args = client.start_workflow.call_args
    assert args.args == ("managed-warehouse.reconcile-model-aliases", {"team_id": 42})
    assert args.kwargs["id"] == "managed-warehouse-model-aliases/42"
    assert args.kwargs["start_signal"] == "refresh"


@pytest.mark.asyncio
async def test_refresh_during_failed_pass_is_processed_afterwards() -> None:
    entered: asyncio.Queue[int] = asyncio.Queue()
    releases = [asyncio.Event(), asyncio.Event(), asyncio.Event()]
    calls = 0

    @activity.defn(name="reconcile_trino_model_aliases_activity")
    async def reconcile(inputs: ModelAliasInputs) -> ModelAliasReconciliation:
        nonlocal calls
        attempt = calls
        calls += 1
        await entered.put(attempt)
        await releases[attempt].wait()
        if attempt == 0:
            raise ApplicationError("Catalog temporarily unavailable", non_retryable=True)
        return ModelAliasReconciliation(published=1)

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
            try:
                assert await asyncio.wait_for(entered.get(), timeout=10) == 0
                await handle.signal(ReconcileModelAliasesWorkflow.refresh)
                assert calls == 1
                releases[0].set()
                assert await asyncio.wait_for(entered.get(), timeout=10) == 1
                assert (await handle.query(ReconcileModelAliasesWorkflow.status)).errors
                await handle.signal(ReconcileModelAliasesWorkflow.refresh)
                releases[1].set()
                assert await asyncio.wait_for(entered.get(), timeout=10) == 2
                assert await handle.query(ReconcileModelAliasesWorkflow.status) == ModelAliasReconciliation(published=1)
            finally:
                for release in releases:
                    release.set()
                await handle.cancel()
