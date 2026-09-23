from datetime import datetime, timedelta
from uuid import UUID

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.common.utils import asyncify

    from products.tasks.backend.logic.services.gateway_usage import process_pending_gateway_usage
    from products.tasks.backend.models import TaskRun


@frozen
class GatewayUsageInput:
    run_id: str
    team_id: int
    retry_until: datetime | None = None


@activity.defn
@asyncify
def reconcile_gateway_usage(input: GatewayUsageInput) -> int:
    try:
        process_pending_gateway_usage(run_id=UUID(input.run_id), team_id=input.team_id)
        state = TaskRun.objects.get(id=input.run_id, team_id=input.team_id).state or {}
        return len(state.get("unprocessed_request_ids", []))
    except TaskRun.DoesNotExist:
        return 0


@workflow.defn(name="task-run-gateway-usage")
class TaskRunGatewayUsageWorkflow(PostHogWorkflow):
    inputs_cls = GatewayUsageInput

    def __init__(self) -> None:
        self._wakeups = 0
        self._retry_until: datetime | None = None

    @workflow.signal
    def requests_available(self) -> None:
        self._wakeups += 1
        self._retry_until = workflow.now() + timedelta(days=1)

    @workflow.run
    async def run(self, input: GatewayUsageInput) -> None:
        self._retry_until = max(
            self._retry_until or workflow.now(), input.retry_until or workflow.now() + timedelta(days=1)
        )
        delay = 30
        pending: int | None = None
        while workflow.now() < self._retry_until:
            wakeups = self._wakeups
            remaining = self._retry_until - workflow.now()
            try:
                pending = await workflow.execute_activity(
                    reconcile_gateway_usage,
                    input,
                    start_to_close_timeout=min(timedelta(seconds=30), remaining),
                    schedule_to_close_timeout=remaining,
                    retry_policy=RetryPolicy(maximum_interval=timedelta(minutes=5)),
                )
            except ActivityError:
                pending = None
            if pending == 0 and wakeups == self._wakeups:
                return
            if workflow.now() >= self._retry_until:
                break

            def requests_available(wakeups: int = wakeups) -> bool:
                return self._wakeups != wakeups

            try:
                await workflow.wait_condition(
                    requests_available,
                    timeout=min(timedelta(seconds=delay), self._retry_until - workflow.now()),
                )
            except TimeoutError:
                pass
            delay = 30 if self._wakeups != wakeups else min(delay * 2, 300)
            if workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(
                    GatewayUsageInput(run_id=input.run_id, team_id=input.team_id, retry_until=self._retry_until)
                )

        # A 404 can be unsettled or permanently unpriced; keep the IDs for recovery.
        workflow.logger.warning(
            "task_gateway_usage.retries_exhausted",
            extra={"run_id": input.run_id, "team_id": input.team_id, "pending": pending},
        )
