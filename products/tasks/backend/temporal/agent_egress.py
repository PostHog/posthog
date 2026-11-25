import asyncio
from collections import Counter
from datetime import timedelta
from typing import Literal

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, is_cancelled_exception

from posthog.temporal.common.base import PostHogWorkflow

from products.tasks.backend.temporal.process_task.activities.agent_egress import (
    AgentEgressCleanupInput,
    AgentEgressExecutionInput,
    AgentEgressProbeInput,
    cleanup_agent_egress,
    prepare_agent_egress,
    probe_agent_egress,
    renew_agent_egress,
)


@workflow.defn(name="agent-egress-probe")
class AgentEgressProbeWorkflow(PostHogWorkflow):
    inputs_cls = AgentEgressProbeInput

    def __init__(self) -> None:
        self._counts: Counter[int] = Counter()

    async def _renew(self, input: AgentEgressExecutionInput, expires_at: float | None = None) -> None:
        while True:
            remaining = None if expires_at is None else expires_at - workflow.now().timestamp()
            if remaining is not None and remaining <= 0:
                return
            await workflow.sleep(10 if remaining is None else min(10, remaining))
            if expires_at is not None and workflow.now().timestamp() >= expires_at:
                return
            await workflow.execute_activity(
                renew_agent_egress,
                input,
                start_to_close_timeout=timedelta(seconds=10),
                schedule_to_close_timeout=timedelta(seconds=15),
                retry_policy=RetryPolicy(maximum_attempts=2, non_retryable_error_types=["ValueError"]),
            )

    async def _probe(self, input: AgentEgressExecutionInput, duration_seconds: int) -> dict[int, int]:
        deadline = workflow.now() + timedelta(seconds=duration_seconds)
        while workflow.now() < deadline:
            self._counts.update(
                await workflow.execute_activity(
                    probe_agent_egress,
                    input,
                    schedule_to_close_timeout=timedelta(minutes=3),
                    heartbeat_timeout=timedelta(seconds=10),
                    retry_policy=RetryPolicy(maximum_attempts=2, non_retryable_error_types=["ValueError"]),
                )
            )
            await workflow.sleep(max(0, min(10, (deadline - workflow.now()).total_seconds())))
        return dict(self._counts)

    @workflow.run
    async def run(self, input: AgentEgressProbeInput) -> dict[int, int]:
        recoverable = workflow.patched("agent-egress-recoverable-provisioning")
        execution = AgentEgressExecutionInput(
            probe=input,
            execution_id=str(workflow.uuid4()),
            provisioning_deadline=(workflow.now() + timedelta(minutes=3)).timestamp() if recoverable else None,
        )
        sandbox_id: str | None = None
        reason: Literal["completed", "cancelled", "failed"] = "failed"
        tasks: list[asyncio.Task[None] | asyncio.Task[dict[int, int]]] = []
        try:
            prepared = await workflow.execute_activity(
                prepare_agent_egress,
                execution,
                schedule_to_close_timeout=timedelta(minutes=3),
                start_to_close_timeout=timedelta(seconds=60) if recoverable else None,
                heartbeat_timeout=timedelta(seconds=10) if recoverable else None,
                retry_policy=RetryPolicy(maximum_attempts=3, non_retryable_error_types=["ValueError"])
                if recoverable
                else RetryPolicy(maximum_attempts=1),
            )
            sandbox_id = prepared.sandbox_id
            renewal = asyncio.create_task(self._renew(execution, prepared.enrollment_expires_at))
            probing = asyncio.create_task(self._probe(execution, prepared.duration_seconds))
            tasks = [renewal, probing]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if prepared.enrollment_expires_at is not None:
                if probing in done:
                    try:
                        await probing
                    except Exception as error:
                        if (
                            isinstance(error, ActivityError)
                            and isinstance(error.cause, ApplicationError)
                            and error.cause.type == "AgentEgressRunEnded"
                        ):
                            raise
                        workflow.logger.warning("agent_egress_diagnostics_failed", extra={"run_id": input.run_id})
                await renewal
                result = dict(self._counts)
            else:
                if renewal in done:
                    await renewal
                result = await probing
            reason = "completed"
            return result
        except BaseException as error:
            if (
                isinstance(error, ActivityError)
                and isinstance(error.cause, ApplicationError)
                and error.cause.type == "AgentEgressRunEnded"
                and len(error.cause.details) == 1
                and error.cause.details[0] in ("completed", "cancelled", "failed")
            ):
                reason = error.cause.details[0]
                if reason == "cancelled" and (
                    not workflow.patched("agent-egress-observed-stop-completes")
                    or workflow.cancellation_reason() is not None
                ):
                    raise asyncio.CancelledError from error
                return dict(self._counts)
            if is_cancelled_exception(error):
                reason = "cancelled"
            raise
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            bounded_cleanup = (
                workflow.patched("agent-egress-bounded-observation-cleanup") and input.sandbox_id is not None
            )
            try:
                await asyncio.shield(
                    workflow.execute_activity(
                        cleanup_agent_egress,
                        AgentEgressCleanupInput(execution=execution, sandbox_id=sandbox_id, reason=reason),
                        schedule_to_close_timeout=timedelta(seconds=10) if bounded_cleanup else None,
                        start_to_close_timeout=timedelta(seconds=10 if bounded_cleanup else 30),
                        retry_policy=RetryPolicy(maximum_attempts=1 if bounded_cleanup else 3),
                    )
                )
            except Exception:
                if reason == "completed":
                    raise
                workflow.logger.exception("agent_egress_probe_cleanup_failed")
