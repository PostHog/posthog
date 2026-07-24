import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .activities import BakeDevStackImageInput, bake_and_publish_dev_stack_image

BAKE_ACTIVITY_TIMEOUT = timedelta(hours=2)


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
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
