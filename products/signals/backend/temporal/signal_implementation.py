"""Finalize a signal handoff after its implementation task settles."""

from datetime import timedelta
from hashlib import sha256

import temporalio
from temporalio import workflow
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import RetryPolicy

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.signal_handoffs import publish_handoff, record_task_cost
from products.tasks.backend.facade import api as tasks_facade


@frozen
class SignalImplementationInput:
    team_id: int
    signal_keys: tuple[str, ...]
    run_id: str | None = None


@temporalio.activity.defn
@scoped_temporal()
@close_db_connections
async def finalize_signal_implementation_activity(input: SignalImplementationInput) -> bool:
    if input.run_id:
        run = await database_sync_to_async(tasks_facade.get_task_run, thread_sensitive=False)(
            input.run_id, input.team_id
        )
        if run is None:
            raise ValueError(f"Implementation task run {input.run_id} is missing")
        if not run.workflow_id:
            raise ValueError(f"Implementation task run {input.run_id} has no workflow")
        client = await async_connect()
        description = await client.get_workflow_handle(run.workflow_id).describe()
        if description.status not in {
            WorkflowExecutionStatus.COMPLETED,
            WorkflowExecutionStatus.FAILED,
            WorkflowExecutionStatus.CANCELED,
            WorkflowExecutionStatus.TERMINATED,
            WorkflowExecutionStatus.TIMED_OUT,
        }:
            return False
        await record_task_cost(input.signal_keys[0], input.team_id, str(run.task_id), "implementation")

    for signal_key in input.signal_keys:
        await publish_handoff(signal_key, input.team_id)
    return True


@temporalio.workflow.defn(name="signal-implementation-finalizer")
class SignalImplementationFinalizerWorkflow:
    @staticmethod
    def workflow_id_for(team_id: int, signal_keys: tuple[str, ...]) -> str:
        if len(signal_keys) == 1:
            return f"signals-implementation-finalizer:{team_id}:{signal_keys[0]}"
        key_hash = sha256("\0".join(sorted(signal_keys)).encode()).hexdigest()[:16]
        return f"signals-implementation-finalizer:{team_id}:batch:{key_hash}"

    @temporalio.workflow.run
    async def run(self, input: SignalImplementationInput) -> None:
        while not await workflow.execute_activity(
            finalize_signal_implementation_activity,
            input,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        ):
            await workflow.sleep(timedelta(seconds=60))
