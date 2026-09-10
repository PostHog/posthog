"""Finalize a signal handoff after its implementation task settles."""

from datetime import datetime, timedelta

import temporalio
from temporalio import workflow
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.signal_handoffs import add_task_cost, publish_handoff, read_handoff, write_handoff
from products.signals.backend.temporal.signal_queries import (
    WaitForClickHouseInput,
    WaitForClickHouseMode,
    WaitForClickHouseSignal,
    wait_for_signal_in_clickhouse_activity,
)
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.billing import get_task_spend


@frozen
class SignalImplementationInput:
    team_id: int
    signal_key: str
    task_id: str | None = None
    run_id: str | None = None


@frozen
class FinalizedSignal:
    signal_id: str
    timestamp: datetime
    inserted_at: datetime | None = None


@temporalio.activity.defn
@scoped_temporal()
@close_db_connections
async def finalize_signal_implementation_activity(input: SignalImplementationInput) -> FinalizedSignal:
    if input.run_id:
        run = await database_sync_to_async(tasks_facade.get_task_run, thread_sensitive=False)(
            input.run_id, input.team_id
        )
        if run is None:
            raise ValueError(f"Implementation task run {input.run_id} is missing")
        if not run.workflow_id:
            raise ValueError(f"Implementation task run {input.run_id} has no workflow")
        async with Heartbeater():
            client = await async_connect()
            try:
                await client.get_workflow_handle(run.workflow_id).result()
            except WorkflowFailureError:
                # A failed or canceled run still incurred spend and must finish the signal handoff.
                pass
        task_id = input.task_id or str(run.task_id)
        spend = await database_sync_to_async(get_task_spend, thread_sensitive=False)(input.team_id, task_id)
        handoff = await read_handoff(input.signal_key, input.team_id)
        add_task_cost(handoff, task_id, spend, "implementation")
        await write_handoff(handoff)

    await publish_handoff(input.signal_key, input.team_id)
    handoff = await read_handoff(input.signal_key, input.team_id)
    return FinalizedSignal(
        signal_id=handoff.signal.signal_id,
        timestamp=handoff.signal.timestamp,
        inserted_at=handoff.signal.inserted_at,
    )


@temporalio.activity.defn
@scoped_temporal()
async def release_signal_key_activity(input: SignalImplementationInput) -> None:
    from products.signals.backend.temporal.grouping_v2 import (
        TeamSignalGroupingV2Workflow,  # noqa: PLC0415 - avoids the activity registration cycle
    )

    client = await async_connect()
    handle = client.get_workflow_handle(TeamSignalGroupingV2Workflow.workflow_id_for(input.team_id))
    await handle.signal("release_signal_key", input.signal_key)


@temporalio.workflow.defn(name="signal-implementation-finalizer")
class SignalImplementationFinalizerWorkflow:
    @staticmethod
    def workflow_id_for(team_id: int, signal_key: str) -> str:
        return f"signals-implementation-finalizer:{team_id}:{signal_key}"

    @temporalio.workflow.run
    async def run(self, input: SignalImplementationInput) -> None:
        finalized: FinalizedSignal = await workflow.execute_activity(
            finalize_signal_implementation_activity,
            input,
            start_to_close_timeout=timedelta(hours=5),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        await workflow.execute_activity(
            wait_for_signal_in_clickhouse_activity,
            WaitForClickHouseInput(
                team_id=input.team_id,
                signals=[
                    WaitForClickHouseSignal(
                        signal_id=finalized.signal_id,
                        timestamp=finalized.timestamp,
                        inserted_at=finalized.inserted_at,
                    )
                ],
                mode=WaitForClickHouseMode.CH_CONFIRMED,
                require_visible=True,
            ),
            start_to_close_timeout=timedelta(hours=1),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        await workflow.execute_activity(
            release_signal_key_activity,
            input,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
