from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.replay_vision.backend.temporal.gemini_cleanup_sweep.constants import (
    SWEEP_ACTIVITY_HEARTBEAT_TIMEOUT,
    SWEEP_ACTIVITY_TIMEOUT,
    WORKFLOW_NAME,
)
from products.replay_vision.backend.temporal.gemini_cleanup_sweep.types import CleanupSweepInputs

with workflow.unsafe.imports_passed_through():
    from products.replay_vision.backend.temporal.gemini_cleanup_sweep.activities import sweep_gemini_files_activity


@workflow.defn(name=WORKFLOW_NAME)
class ReplayVisionGeminiCleanupSweepWorkflow(PostHogWorkflow):
    inputs_cls = CleanupSweepInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: CleanupSweepInputs) -> dict[str, Any]:
        result = await workflow.execute_activity(
            sweep_gemini_files_activity,
            inputs,
            start_to_close_timeout=SWEEP_ACTIVITY_TIMEOUT,
            heartbeat_timeout=SWEEP_ACTIVITY_HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        return result.model_dump()
