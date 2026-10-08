import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.posthog_ai.backend.temporal.activities import (
    MirrorConversationInputs,
    mirror_conversation_to_task_activity,
)

MIRROR_ACTIVITY_TIMEOUT = 2 * 60  # 2 minutes
MIRROR_ACTIVITY_MAX_ATTEMPTS = 3


@workflow.defn(name="conversation-mirror")
class ConversationMirrorWorkflow(PostHogWorkflow):
    """Copy a LangGraph conversation's newest turn into its task.

    The chat workflow starts this as a detached child and closes without waiting for it. The chat
    workflow's id is fixed per conversation, so a follow-up sent while it is still open joins the
    old execution and loses its message; keeping the copy out of that workflow keeps that window as
    short as it was before the copy existed.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> MirrorConversationInputs:
        return MirrorConversationInputs(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, inputs: MirrorConversationInputs) -> None:
        await workflow.execute_activity(
            mirror_conversation_to_task_activity,
            inputs,
            start_to_close_timeout=timedelta(seconds=MIRROR_ACTIVITY_TIMEOUT),
            retry_policy=RetryPolicy(maximum_attempts=MIRROR_ACTIVITY_MAX_ATTEMPTS),
        )
