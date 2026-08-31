import asyncio
from datetime import datetime, timedelta

import temporalio.common
from temporalio import workflow

from products.subscriptions.backend.pulse.temporal.activities import (
    advance_pulse_workflow,
    cancel_pulse_workflow,
    finalize_timed_out_pulse_workflow,
)
from products.subscriptions.backend.pulse.temporal.inputs import PulseWorkflowInput, PulseWorkflowResult

PULSE_ACTIVITY_RETRY_POLICY = temporalio.common.RetryPolicy(
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(minutes=1),
    maximum_attempts=3,
)
PULSE_POLL_INTERVAL = timedelta(seconds=10)


def finalization_timeout(input: PulseWorkflowInput) -> timedelta:
    return timedelta(seconds=max(1, input.proactive_snapshot.finalization_margin_seconds))


def finalization_deadline(input: PulseWorkflowInput) -> datetime:
    return input.deadline - finalization_timeout(input)


@workflow.defn(name="process-proactive-subscription")
class PulseWorkflow:
    @workflow.run
    async def run(self, input: PulseWorkflowInput) -> PulseWorkflowResult:
        try:
            cutoff = finalization_deadline(input)
            while workflow.now() < cutoff:
                remaining = cutoff - workflow.now()
                if remaining <= timedelta(seconds=1):
                    break
                activity_timeout = min(timedelta(minutes=2), timedelta(seconds=int(remaining.total_seconds())))
                result = await workflow.execute_activity(
                    advance_pulse_workflow,
                    input,
                    start_to_close_timeout=activity_timeout,
                    schedule_to_close_timeout=activity_timeout,
                    retry_policy=PULSE_ACTIVITY_RETRY_POLICY,
                )
                if result is not None:
                    return result
                remaining = cutoff - workflow.now()
                if remaining.total_seconds() > 0:
                    await workflow.sleep(min(PULSE_POLL_INTERVAL, remaining).total_seconds())
            timeout = timedelta(seconds=max(1, (input.deadline - workflow.now()).total_seconds()))
            return await workflow.execute_activity(
                finalize_timed_out_pulse_workflow,
                input,
                start_to_close_timeout=min(timedelta(minutes=2), timeout),
                schedule_to_close_timeout=timeout,
                retry_policy=PULSE_ACTIVITY_RETRY_POLICY,
            )
        except asyncio.CancelledError:
            await workflow.execute_activity(
                cancel_pulse_workflow,
                input,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=PULSE_ACTIVITY_RETRY_POLICY,
            )
            raise
