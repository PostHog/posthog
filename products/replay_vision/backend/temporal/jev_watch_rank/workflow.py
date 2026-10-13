from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.replay_vision.backend.temporal.jev_watch_rank.constants import (
    SWEEP_ACTIVITY_HEARTBEAT_TIMEOUT,
    SWEEP_ACTIVITY_TIMEOUT,
    WORKFLOW_NAME,
)
from products.replay_vision.backend.temporal.jev_watch_rank.types import JevWatchRankSweepInputs

with workflow.unsafe.imports_passed_through():
    from products.replay_vision.backend.temporal.jev_watch_rank.activities import judge_watch_ranks_activity


@workflow.defn(name=WORKFLOW_NAME)
class ReplayVisionJevWatchRankWorkflow(PostHogWorkflow):
    inputs_cls = JevWatchRankSweepInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: JevWatchRankSweepInputs) -> dict[str, Any]:
        result = await workflow.execute_activity(
            judge_watch_ranks_activity,
            inputs,
            start_to_close_timeout=SWEEP_ACTIVITY_TIMEOUT,
            heartbeat_timeout=SWEEP_ACTIVITY_HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        return result.model_dump()
