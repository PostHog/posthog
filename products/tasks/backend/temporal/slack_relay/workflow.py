import typing
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.slack_app.backend.facade.temporal import (
        PresentSlackReplyInput,
        SlackReplyPresentationGateInput,
        is_slack_reply_presentation_enabled_activity,
        present_slack_reply_activity,
    )

from .activities import RelaySlackMessageInput, relay_slack_message

_PATCH_ID_REPLY_PRESENTATION = "posthog-code-agent-relay-reply-presentation"


@workflow.defn(name="posthog-code-agent-relay")
class PostHogCodeAgentRelayWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> typing.Any:
        raise NotImplementedError("PostHogCodeAgentRelayWorkflow is not intended to be started via CLI")

    @workflow.run
    async def run(self, input: RelaySlackMessageInput) -> None:
        delivered = await workflow.execute_activity(
            relay_slack_message,
            input,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if workflow.patched(_PATCH_ID_REPLY_PRESENTATION) and delivered and input.offer_presentation:
            await self._present(input)

    async def _present(self, input: RelaySlackMessageInput) -> None:
        """Components under the delivered answer, as a message of their own that grows as they arrive.
        Best effort: the answer is already in the thread."""
        try:
            if not await workflow.execute_activity(
                is_slack_reply_presentation_enabled_activity,
                SlackReplyPresentationGateInput(run_id=input.run_id),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            ):
                return
            await workflow.execute_activity(
                present_slack_reply_activity,
                PresentSlackReplyInput(run_id=input.run_id, answer_markdown=input.text, trace_id=input.trace_id),
                start_to_close_timeout=timedelta(seconds=30),
                # One attempt, because a retry would post the components a second time.
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except ActivityError:
            workflow.logger.warning("slack_relay_presentation_failed", extra={"run_id": input.run_id})
