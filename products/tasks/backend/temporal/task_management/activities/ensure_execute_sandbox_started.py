"""Signal-With-Start the ExecuteSandbox workflow.

Workflow code cannot call `client.start_workflow(..., start_signal=...)`
directly — Signal-With-Start is a client-side primitive. This activity is the
thin wrapper that lets the orchestrator (TaskManagementWorkflow) use it.

The activity is idempotent: if the ExecuteSandbox workflow is already running
under `workflow_id`, Temporal just delivers the bootstrap signal to the
existing execution. If no workflow is running, it starts a fresh one with the
provided input *and* the bootstrap signal in the initial signal queue. Either
way, no race, no `WorkflowAlreadyStartedError` to catch.
"""

from dataclasses import dataclass

from django.conf import settings

from temporalio import activity
from temporalio.common import WorkflowIDReusePolicy

from posthog.temporal.common.client import async_connect

from products.tasks.backend.temporal.execute_sandbox.workflow import PARENT_ATTACHED_SIGNAL, ExecuteSandboxInput
from products.tasks.backend.temporal.observability import log_activity_execution


@dataclass
class EnsureExecuteSandboxStartedInput:
    workflow_id: str
    workflow_input: ExecuteSandboxInput
    bootstrap_ack_id: str


@activity.defn
async def ensure_execute_sandbox_started(input: EnsureExecuteSandboxStartedInput) -> None:
    with log_activity_execution(
        "ensure_execute_sandbox_started",
        run_id=input.workflow_input.run_id,
        workflow_id=input.workflow_id,
        bootstrap_ack_id=input.bootstrap_ack_id,
    ):
        client = await async_connect()
        await client.start_workflow(
            "execute-sandbox",
            input.workflow_input,
            id=input.workflow_id,
            task_queue=settings.TASKS_TASK_QUEUE,
            # CLOSED prior execution under this id → ok to start a fresh one.
            # RUNNING prior execution → Signal-With-Start delivers the signal
            # to it without starting a new one; the start args are ignored
            # in that case, which is fine — the workflow input is deterministic.
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            start_signal=PARENT_ATTACHED_SIGNAL,
            start_signal_args=[input.bootstrap_ack_id, input.workflow_input.parent_workflow_id],
            # No workflow-execution retry policy: ExecuteSandboxWorkflow
            # catches its own exceptions and returns ExecuteSandboxOutput, so
            # auto-restart would only fire on Temporal-level failures (worker
            # crash etc.) and would re-reap + re-provision a sandbox per
            # restart. Recovery from those failures lives at the orchestrator
            # level via the ACK-retry / re-bootstrap path.
        )
