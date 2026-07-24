import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .activities import BakeDevStackImageInput, bake_and_publish_dev_stack_image

# Matches the bake sandbox's TTL: the 90-minute bake execution budget plus the
# published-image snapshot attempts (each up to 30 minutes, retried in place).
BAKE_ACTIVITY_TIMEOUT = timedelta(hours=3)


@workflow.defn(name="bake-dev-stack-image")
class BakeDevStackImageWorkflow(PostHogWorkflow):
    """Bakes and republishes the prebaked PostHog dev-stack VM image.

    Dispatched nightly (see `bake_dev_stack_image_task` in the tasks facade) so the
    baked migration state stays close to master and task-time `hogli start` only
    applies a day's worth of migrations.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BakeDevStackImageInput:
        loaded = json.loads(inputs[0])
        return BakeDevStackImageInput(**{k: v for k, v in loaded.items() if k == "publish_name"})

    @workflow.run
    async def run(self, input: BakeDevStackImageInput) -> str:
        return await workflow.execute_activity(
            bake_and_publish_dev_stack_image,
            input,
            start_to_close_timeout=BAKE_ACTIVITY_TIMEOUT,
            # At most one automated re-bake: each attempt is a full 15-25 minute stack build.
            # The workflow itself is started with maximum_attempts=1 (see temporal/client.py)
            # so these attempts never multiply; the nightly schedule is the outer retry loop.
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
