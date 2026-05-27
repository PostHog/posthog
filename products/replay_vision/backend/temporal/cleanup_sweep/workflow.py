"""Daily sweep that prunes old observation rows and reaps stranded in-flight ones."""

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.replay_vision.backend.temporal.cleanup_sweep.constants import (
    PRUNE_ACTIVITY_TIMEOUT,
    PRUNE_HEARTBEAT_TIMEOUT,
    REAP_ACTIVITY_TIMEOUT,
    REAP_HEARTBEAT_TIMEOUT,
    WORKFLOW_NAME,
)
from products.replay_vision.backend.temporal.cleanup_sweep.types import CleanupSweepInputs, CleanupSweepResult

with workflow.unsafe.imports_passed_through():
    from products.replay_vision.backend.temporal.cleanup_sweep.activities import (
        prune_old_observations_activity,
        reap_stranded_observations_activity,
    )


@workflow.defn(name=WORKFLOW_NAME)
class ReplayVisionCleanupSweepWorkflow(PostHogWorkflow):
    inputs_cls = CleanupSweepInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: CleanupSweepInputs) -> CleanupSweepResult:
        prune = await workflow.execute_activity(
            prune_old_observations_activity,
            inputs,
            start_to_close_timeout=PRUNE_ACTIVITY_TIMEOUT,
            heartbeat_timeout=PRUNE_HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        reap = await workflow.execute_activity(
            reap_stranded_observations_activity,
            inputs,
            start_to_close_timeout=REAP_ACTIVITY_TIMEOUT,
            heartbeat_timeout=REAP_HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        return CleanupSweepResult(prune=prune, reap=reap)
