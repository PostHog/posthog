import asyncio
import logging
from datetime import timedelta
from typing import Literal
from uuid import uuid4

import pytest

from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.common.heartbeat import Heartbeater

from products.tasks.backend.temporal.agent_egress import AgentEgressProbeWorkflow
from products.tasks.backend.temporal.process_task.activities.agent_egress import (
    AgentEgressCleanupInput,
    AgentEgressExecutionInput,
    AgentEgressPrepared,
    AgentEgressProbeInput,
)

Outcome = Literal["completed", "cancelled", "renewal_failed", "renewal_retry", "probe_rejected", "prepare_failed"]


class EgressActivities:
    def __init__(self, outcome: Outcome, *, cleanup_fails: bool) -> None:
        self.outcome = outcome
        self.cleanup_fails = cleanup_fails
        self.probe_attempts = 0
        self.execution: AgentEgressExecutionInput | None = None
        self.cleanup: AgentEgressCleanupInput | None = None
        self.probing = asyncio.Event()
        self.closed = asyncio.Event()

    @activity.defn(name="prepare_agent_egress")
    async def prepare(self, input: AgentEgressExecutionInput) -> AgentEgressPrepared:
        self.execution = input
        if self.outcome == "prepare_failed":
            raise ValueError("Provider write failed")
        return AgentEgressPrepared(
            sandbox_id="sb-egress-test",
            duration_seconds=1 if self.outcome in ("completed", "renewal_retry", "probe_rejected") else 60,
        )

    @activity.defn(name="renew_agent_egress")
    async def renew(self, input: AgentEgressExecutionInput) -> None:
        assert input == self.execution
        if self.outcome == "renewal_failed":
            raise ApplicationError("Execution lease expired", non_retryable=True)
        if self.outcome == "renewal_retry":
            if activity.info().attempt == 1:
                raise ApplicationError("Registry temporarily unavailable")
            self.closed.set()

    @activity.defn(name="probe_agent_egress")
    async def probe(self, input: AgentEgressExecutionInput) -> dict[int, int]:
        assert input == self.execution
        self.probing.set()
        self.probe_attempts += 1
        if self.outcome == "probe_rejected":
            raise ValueError("The registered probe request failed")
        if self.outcome != "completed":
            async with Heartbeater(factor=5):
                await self.closed.wait()
        return {204: 3}

    @activity.defn(name="cleanup_agent_egress")
    async def close(self, input: AgentEgressCleanupInput) -> None:
        self.cleanup = input
        self.closed.set()
        if self.cleanup_fails:
            raise OSError("Provider cleanup unavailable")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome", ["completed", "cancelled", "renewal_failed", "renewal_retry", "probe_rejected", "prepare_failed"]
)
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_workflow_cleans_up_its_execution(
    outcome: Outcome, cleanup_fails: bool, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    activities = EgressActivities(outcome, cleanup_fails=cleanup_fails)
    input = AgentEgressProbeInput(config_path="/run/egress/probe.json", team_id=1, run_id=str(uuid4()))
    queue = f"agent-egress-test-{uuid4()}"
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=queue,
            workflows=[AgentEgressProbeWorkflow],
            activities=[activities.prepare, activities.renew, activities.probe, activities.close],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await environment.client.start_workflow(
                AgentEgressProbeWorkflow.run,
                input,
                id=queue,
                task_queue=queue,
                execution_timeout=timedelta(minutes=2),
            )
            try:
                if outcome != "prepare_failed":
                    await asyncio.wait_for(activities.probing.wait(), timeout=15)
                if outcome == "cancelled":
                    await handle.cancel()
                elif outcome in ("renewal_failed", "renewal_retry"):
                    await environment.sleep(11)
                if outcome in ("completed", "renewal_retry") and not cleanup_fails:
                    assert await asyncio.wait_for(handle.result(), timeout=15) == {204: 3}
                else:
                    with pytest.raises(WorkflowFailureError) as failure:
                        await asyncio.wait_for(handle.result(), timeout=15)
                    expected = CancelledError if outcome == "cancelled" else ActivityError
                    assert isinstance(failure.value.cause, expected)
                    if outcome != "cancelled":
                        assert isinstance(failure.value.cause, ActivityError)
                        assert isinstance(failure.value.cause.cause, ApplicationError)
                        expected_message = {
                            "renewal_failed": "Execution lease expired",
                            "probe_rejected": "The registered probe request failed",
                            "prepare_failed": "Provider write failed",
                        }.get(outcome, "Provider cleanup unavailable")
                        assert failure.value.cause.cause.message == expected_message
                if outcome == "probe_rejected":
                    assert activities.probe_attempts == 1
                assert activities.execution is not None
                assert activities.execution.probe == input
                assert activities.cleanup == AgentEgressCleanupInput(
                    execution=activities.execution,
                    sandbox_id=None if outcome == "prepare_failed" else "sb-egress-test",
                    reason="failed"
                    if outcome in ("renewal_failed", "probe_rejected", "prepare_failed")
                    else "cancelled"
                    if outcome == "cancelled"
                    else "completed",
                )
            finally:
                activities.closed.set()
