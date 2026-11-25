import asyncio
import logging
from datetime import timedelta
from typing import Literal
from uuid import uuid4

import pytest

from temporalio import activity
from temporalio.client import WorkflowExecutionStatus, WorkflowFailureError
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

from products.tasks.backend.logic.services.agent_egress import AGENT_EGRESS_LEASE_DURATION
from products.tasks.backend.temporal.agent_egress import AgentEgressProbeWorkflow
from products.tasks.backend.temporal.process_task.activities.agent_egress import (
    AgentEgressCleanupInput,
    AgentEgressExecutionInput,
    AgentEgressPrepared,
    AgentEgressProbeInput,
)
from products.tasks.backend.temporal.process_task.activities.cleanup_sandbox import CleanupSandboxInput
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import (
    GetTaskProcessingContextInput,
    TaskProcessingContext,
)
from products.tasks.backend.temporal.process_task.activities.read_sandbox_logs import ReadSandboxLogsInput
from products.tasks.backend.temporal.process_task.activities.update_task_run_status import UpdateTaskRunStatusInput
from products.tasks.backend.temporal.process_task.workflow import (
    ProcessTaskInput,
    ProcessTaskWorkflow,
    ResumedSandboxState,
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
    "run_cancelled",
    "run_completed",
    "run_failed",
]


class EgressActivities:
    def __init__(self, outcome: Outcome, *, cleanup_fails: bool, cleanup_blocked: bool = False) -> None:
        self.outcome = outcome
        self.cleanup_fails = cleanup_fails
        self.cleanup_blocked = cleanup_blocked
        self.cleanup_attempts = 0
        self.probe_attempts = 0
        self.prepare_attempts = 0
        self.renewal_attempts = 0
        self.execution: AgentEgressExecutionInput | None = None
        self.cleanup: AgentEgressCleanupInput | None = None
        self.preparing = asyncio.Event()
        self.probing = asyncio.Event()
        self.renewed = asyncio.Event()
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
            if input.probe.sandbox_expires_at is not None
            or self.outcome in ("completed", "renewal_retry", "probe_rejected", "prepare_retry", "prepare_timeout")
            else 60,
            enrollment_expires_at=input.probe.sandbox_expires_at,
        )

    @activity.defn(name="renew_agent_egress")
    async def renew(self, input: AgentEgressExecutionInput) -> None:
        assert input == self.execution
        self.renewal_attempts += 1
        if self.outcome == "renewal_failed":
            raise ApplicationError("Execution lease expired", non_retryable=True)
        if self.outcome in ("run_cancelled", "run_completed", "run_failed"):
            raise ApplicationError(
                "The task run has ended",
                self.outcome.removeprefix("run_"),
                type="AgentEgressRunEnded",
                non_retryable=True,
            )
        if self.outcome == "renewal_retry":
            if activity.info().attempt == 1:
                raise ApplicationError("Registry temporarily unavailable")
            self.closed.set()
        self.renewed.set()

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
@pytest.mark.parametrize("keep_enrollment,cleanup_unavailable", [(True, False), (False, False), (True, True)])
async def test_task_continuation_reenrolls_after_previous_child_cleanup(
    keep_enrollment: bool, cleanup_unavailable: bool, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    children: dict[str, EgressActivities] = {}
    owners: list[str] = []
    contexts: list[GetTaskProcessingContextInput] = []
    prepared: asyncio.Queue[AgentEgressExecutionInput] = asyncio.Queue()
    continued = asyncio.Event()
    sandbox_cleanup: list[str] = []
    statuses: list[str] = []
    lease_expiries: dict[str, float] = {}
    preparation_attempts: list[AgentEgressExecutionInput] = []
    cleanup_started = asyncio.Event()
    ownership_conflicted = asyncio.Event()

    @activity.defn(name="get_task_processing_context")
    async def context(input: GetTaskProcessingContextInput) -> TaskProcessingContext:
        contexts.append(input)
        if len(contexts) == 2:
            continued.set()
        return TaskProcessingContext(
            task_id=str(uuid4()),
            run_id=input.run_id,
            team_id=1,
            team_uuid=str(uuid4()),
            organization_id=str(uuid4()),
            github_integration_id=None,
            repository=None,
            distinct_id="egress-handoff-test",
            environment="cloud",
            create_pr=False,
            use_modal_resume_snapshots=False,
            sandbox_event_ingest_enabled=True,
            agent_egress_observation_config="",
            agent_egress_enrollment_enabled=True,
            agent_egress_maintain_for_run=len(contexts) == 1 or keep_enrollment,
            continue_as_new_enabled=len(contexts) == 1,
            continue_as_new_history_threshold=40,
        )

    @activity.defn(name="prepare_agent_egress")
    async def prepare(input: AgentEgressExecutionInput) -> AgentEgressPrepared:
        preparation_attempts.append(input)
        now = (await environment.get_current_time()).timestamp()
        if any(not child.closed.is_set() and lease_expiries[key] > now for key, child in children.items()):
            assert cleanup_unavailable
            ownership_conflicted.set()
            raise ApplicationError(
                "The previous execution still owns the lease",
                type="AgentEgressOwnershipConflict",
                next_retry_delay=AGENT_EGRESS_LEASE_DURATION,
            )
        child = EgressActivities("completed", cleanup_fails=False)
        children[input.execution_id] = child
        lease_expiries[input.execution_id] = now + AGENT_EGRESS_LEASE_DURATION.total_seconds()
        workflow_run_id = activity.info().workflow_run_id
        assert workflow_run_id is not None
        owners.append(workflow_run_id)
        result = await child.prepare(input)
        prepared.put_nowait(input)
        return result

    @activity.defn(name="renew_agent_egress")
    async def renew(input: AgentEgressExecutionInput) -> None:
        await children[input.execution_id].renew(input)
        lease_expiries[input.execution_id] = (
            await environment.get_current_time() + AGENT_EGRESS_LEASE_DURATION
        ).timestamp()

    @activity.defn(name="probe_agent_egress")
    async def probe(input: AgentEgressExecutionInput) -> dict[int, int]:
        return await children[input.execution_id].probe(input)

    @activity.defn(name="cleanup_agent_egress")
    async def close(input: AgentEgressCleanupInput) -> None:
        if cleanup_unavailable and input.execution.execution_id == next(iter(children)):
            cleanup_started.set()
            await asyncio.Future()
        await children[input.execution.execution_id].close(input)

    @activity.defn(name="read_sandbox_logs")
    async def read_logs(input: ReadSandboxLogsInput) -> str:
        return ""

    @activity.defn(name="update_task_run_status")
    async def update_status(input: UpdateTaskRunStatusInput) -> None:
        now = (await environment.get_current_time()).timestamp()
        assert all(child.closed.is_set() or lease_expiries[key] <= now for key, child in children.items())
        statuses.append(input.status)

    @activity.defn(name="cleanup_sandbox")
    async def cleanup(input: CleanupSandboxInput) -> None:
        sandbox_cleanup.append(input.sandbox_id)

    queue = f"agent-egress-handoff-test-{uuid4()}"
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        deadline = await environment.get_current_time() + timedelta(minutes=30)
        input = ProcessTaskInput(
            run_id=str(uuid4()),
            create_pr=False,
            resumed_sandbox=ResumedSandboxState(
                sandbox_id="sb-egress-test",
                sandbox_url="https://sandbox.example.com",
                connect_token=None,
                ci_repetitions=0,
                pr_fingerprint=None,
                pr_progress_emitted=False,
                first_user_message_received=True,
                is_agent_design_enabled=False,
                last_active_time=None,
                sandbox_ttl_expires_at=deadline.isoformat(),
                sandbox_backend="modal",
                agent_egress_maintain_for_run=True,
            ),
        )
        async with Worker(
            environment.client,
            task_queue=queue,
            workflows=[ProcessTaskWorkflow, AgentEgressProbeWorkflow],
            activities=[context, prepare, renew, probe, close, read_logs, update_status, cleanup],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await environment.client.start_workflow(
                ProcessTaskWorkflow.run, input, id=queue, task_queue=queue, execution_timeout=timedelta(minutes=2)
            )
            first = await asyncio.wait_for(prepared.get(), timeout=15)
            await environment.sleep(11)
            assert children[first.execution_id].renewed.is_set()
            for _ in range(40):
                if continued.is_set():
                    break
                await handle.signal(ProcessTaskWorkflow.heartbeat, True)
            if cleanup_unavailable:
                await asyncio.wait_for(cleanup_started.wait(), timeout=15)
                await environment.sleep(11)
            await asyncio.wait_for(continued.wait(), timeout=15)
            assert children[first.execution_id].closed.is_set() is not cleanup_unavailable
            assert sandbox_cleanup == []
            if cleanup_unavailable:
                await asyncio.wait_for(ownership_conflicted.wait(), timeout=15)
                assert len(children) == 1
                await environment.sleep(AGENT_EGRESS_LEASE_DURATION + timedelta(seconds=1))
            if keep_enrollment:
                second = await asyncio.wait_for(prepared.get(), timeout=15)
                assert second.execution_id != first.execution_id
                assert owners[0] != owners[1]
                assert second.probe.sandbox_id == first.probe.sandbox_id == "sb-egress-test"
                assert second.probe.sandbox_expires_at == first.probe.sandbox_expires_at == deadline.timestamp()
                assert len(preparation_attempts) == (3 if cleanup_unavailable else 2)
                if cleanup_unavailable:
                    assert preparation_attempts[-2] == preparation_attempts[-1]
                await environment.sleep(11)
                assert children[second.execution_id].renewed.is_set()
            await handle.signal(ProcessTaskWorkflow.complete_task, args=["completed", None])
            result = await asyncio.wait_for(handle.result(), timeout=15)
            assert result.success
            assert len(contexts) == 2
            assert all(item.resume_agent_egress_enrollment for item in contexts)
            assert len(children) == (2 if keep_enrollment else 1)
            for execution_id, child in children.items():
                lost_cleanup = cleanup_unavailable and execution_id == first.execution_id
                assert child.closed.is_set() is not lost_cleanup
                assert child.cleanup_attempts == (0 if lost_cleanup else 1)
            assert sandbox_cleanup == ["sb-egress-test"]
            assert statuses == ["completed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("probe_fails", [False, True])
@pytest.mark.parametrize(
    "outcome", ["completed", "cancelled", "renewal_failed", "run_cancelled", "run_completed", "run_failed"]
)
async def test_enrollment_outlives_diagnostics(
    probe_fails: bool, outcome: Outcome, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    activities = EgressActivities("probe_rejected" if probe_fails else "completed", cleanup_fails=False)
    queue = f"agent-egress-lifetime-test-{uuid4()}"
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        expires_at = (await environment.get_current_time() + timedelta(seconds=35)).timestamp()
        input = AgentEgressProbeInput(
            config_path="/run/egress/probe.json",
            team_id=1,
            run_id=str(uuid4()),
            sandbox_id="sb-egress-test",
            enrollment=True,
            sandbox_expires_at=expires_at,
        )
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
            await asyncio.wait_for(activities.probing.wait(), timeout=15)
            await environment.sleep(11)
            assert not activities.cleaning.is_set()
            await asyncio.wait_for(activities.renewed.wait(), timeout=15)
            assert activities.probe_attempts == 1
            assert activities.renewal_attempts >= 1
            activities.outcome = outcome
            if outcome == "cancelled":
                await handle.cancel()
            if outcome in ("cancelled", "renewal_failed"):
                with pytest.raises(WorkflowFailureError) as failure:
                    await asyncio.wait_for(handle.result(), timeout=15)
                expected = ActivityError if outcome == "renewal_failed" else CancelledError
                assert isinstance(failure.value.cause, expected)
            else:
                assert await asyncio.wait_for(handle.result(), timeout=15) == ({} if probe_fails else {204: 3})
            assert (await handle.describe()).status == (
                WorkflowExecutionStatus.CANCELED
                if outcome == "cancelled"
                else WorkflowExecutionStatus.FAILED
                if outcome == "renewal_failed"
                else WorkflowExecutionStatus.COMPLETED
            )
            if outcome == "completed":
                assert (await environment.get_current_time()).timestamp() >= expires_at
                assert activities.renewal_attempts >= 3
            assert activities.cleanup is not None
            assert activities.cleanup.reason == (
                "failed"
                if outcome in ("renewal_failed", "run_failed")
                else "cancelled"
                if outcome in ("cancelled", "run_cancelled")
                else "completed"
            )
            assert activities.cleanup_attempts == 1
            assert ("agent_egress_diagnostics_failed" in caplog.text) is probe_fails


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
        "run_cancelled",
        "run_completed",
        "run_failed",
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
                elif outcome in ("renewal_failed", "renewal_retry", "run_cancelled", "run_completed", "run_failed"):
                    await environment.sleep(11)
                if outcome in ("run_completed", "run_failed", "run_cancelled") and (
                    not cleanup_fails or outcome != "run_completed"
                ):
                    assert await asyncio.wait_for(handle.result(), timeout=15) == {}
                elif (
                    outcome in ("completed", "renewal_retry", "prepare_retry", "prepare_timeout") and not cleanup_fails
                ):
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
                assert (await handle.describe()).status == (
                    WorkflowExecutionStatus.CANCELED
                    if outcome == "cancelled"
                    else WorkflowExecutionStatus.COMPLETED
                    if outcome in ("run_cancelled", "run_failed")
                    or (
                        outcome in ("completed", "renewal_retry", "prepare_retry", "prepare_timeout", "run_completed")
                        and not cleanup_fails
                    )
                    else WorkflowExecutionStatus.FAILED
                )
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
                    if outcome in ("renewal_failed", "probe_rejected", "prepare_failed", "run_failed")
                    else "cancelled"
                    if outcome in ("cancelled", "run_cancelled")
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
