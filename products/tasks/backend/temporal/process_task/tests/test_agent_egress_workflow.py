import asyncio
import logging
from datetime import timedelta
from typing import Literal
from uuid import uuid4

import pytest

from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    CancelledError,
    TimeoutError as TemporalTimeoutError,
    TimeoutType,
)
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

Outcome = Literal[
    "completed",
    "cancelled",
    "renewal_failed",
    "renewal_retry",
    "probe_rejected",
    "prepare_failed",
    "prepare_retry",
    "prepare_timeout",
]


class EgressActivities:
    def __init__(self, outcome: Outcome, *, cleanup_fails: bool, cleanup_blocked: bool = False) -> None:
        self.outcome = outcome
        self.cleanup_fails = cleanup_fails
        self.cleanup_blocked = cleanup_blocked
        self.cleanup_attempts = 0
        self.probe_attempts = 0
        self.prepare_attempts = 0
        self.execution: AgentEgressExecutionInput | None = None
        self.cleanup: AgentEgressCleanupInput | None = None
        self.preparing = asyncio.Event()
        self.probing = asyncio.Event()
        self.closed = asyncio.Event()
        self.cleaning = asyncio.Event()
        self.release_cleanup = asyncio.Event()

    @activity.defn(name="prepare_agent_egress")
    async def prepare(self, input: AgentEgressExecutionInput) -> AgentEgressPrepared:
        if self.execution is not None:
            assert input == self.execution
        self.execution = input
        self.prepare_attempts += 1
        self.preparing.set()
        if self.outcome == "prepare_failed":
            raise ValueError("Provider write failed")
        if self.outcome == "prepare_retry" and self.prepare_attempts == 1:
            raise OSError("Provider temporarily unavailable")
        if self.outcome == "prepare_timeout" and self.prepare_attempts == 1:
            await self.closed.wait()
        return AgentEgressPrepared(
            sandbox_id="sb-egress-test",
            duration_seconds=1
            if self.outcome in ("completed", "renewal_retry", "probe_rejected", "prepare_retry", "prepare_timeout")
            else 60,
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
        if self.outcome not in ("completed", "prepare_retry", "prepare_timeout"):
            async with Heartbeater(factor=5):
                await self.closed.wait()
        return {204: 3}

    @activity.defn(name="cleanup_agent_egress")
    async def close(self, input: AgentEgressCleanupInput) -> None:
        self.cleanup = input
        self.cleanup_attempts += 1
        self.cleaning.set()
        self.closed.set()
        if self.cleanup_blocked:
            await self.release_cleanup.wait()
        if self.cleanup_fails:
            raise OSError("Provider cleanup unavailable")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    [
        "completed",
        "cancelled",
        "renewal_failed",
        "renewal_retry",
        "probe_rejected",
        "prepare_failed",
        "prepare_retry",
        "prepare_timeout",
    ],
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
                if outcome == "prepare_timeout":
                    await asyncio.wait_for(activities.preparing.wait(), timeout=15)
                    await environment.sleep(11)
                if outcome != "prepare_failed":
                    await asyncio.wait_for(activities.probing.wait(), timeout=15)
                if outcome == "cancelled":
                    await handle.cancel()
                elif outcome in ("renewal_failed", "renewal_retry"):
                    await environment.sleep(11)
                if outcome in ("completed", "renewal_retry", "prepare_retry", "prepare_timeout") and not cleanup_fails:
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
                assert activities.prepare_attempts == (2 if outcome in ("prepare_retry", "prepare_timeout") else 1)
                assert activities.cleanup_attempts == (3 if cleanup_fails else 1)
                assert activities.execution is not None
                assert activities.execution.probe == input
                assert activities.execution.provisioning_deadline is not None
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


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "cancelled"])
async def test_attached_observation_bounds_cleanup(outcome: Literal["completed", "cancelled"]) -> None:
    activities = EgressActivities(outcome, cleanup_fails=False, cleanup_blocked=True)
    queue = f"agent-egress-cleanup-test-{uuid4()}"
    input = AgentEgressProbeInput(
        config_path="/run/egress/probe.json", team_id=1, run_id=str(uuid4()), sandbox_id="sb-egress-test"
    )
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
            result = asyncio.create_task(handle.result())
            try:
                await asyncio.wait_for(activities.probing.wait(), timeout=15)
                if outcome == "cancelled":
                    await handle.cancel()
                await asyncio.wait_for(activities.cleaning.wait(), timeout=15)
                await environment.sleep(11)
                with pytest.raises(WorkflowFailureError) as failure:
                    await asyncio.wait_for(result, timeout=15)
                if outcome == "cancelled":
                    assert isinstance(failure.value.cause, CancelledError)
                else:
                    assert isinstance(failure.value.cause, ActivityError)
                    assert isinstance(failure.value.cause.cause, TemporalTimeoutError)
                    assert failure.value.cause.cause.type in (TimeoutType.START_TO_CLOSE, TimeoutType.SCHEDULE_TO_CLOSE)
                assert activities.cleanup_attempts == 1
                assert activities.cleanup is not None
                assert activities.cleanup.reason == outcome
                history = await handle.fetch_history()
                scheduled = next(
                    event
                    for event in history.events
                    if event.HasField("activity_task_scheduled_event_attributes")
                    and event.activity_task_scheduled_event_attributes.activity_type.name == "cleanup_agent_egress"
                )
                request = scheduled.activity_task_scheduled_event_attributes
                assert request.schedule_to_close_timeout.ToTimedelta() == timedelta(seconds=10)
                assert request.retry_policy.maximum_attempts == 1
            finally:
                activities.closed.set()
                activities.release_cleanup.set()
                if not result.done():
                    await handle.cancel()
                    result.cancel()
                await asyncio.gather(result, return_exceptions=True)
