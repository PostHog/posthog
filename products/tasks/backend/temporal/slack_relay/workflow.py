import typing
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .activities import RelaySlackMessageInput, relay_slack_message


@workflow.defn(name="twig-agent-relay")
class TwigAgentRelayWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> typing.Any:
        raise NotImplementedError("TwigAgentRelayWorkflow is not intended to be started via CLI")

    @workflow.run
    async def run(self, input: RelaySlackMessageInput) -> None:
        await workflow.execute_activity(
            relay_slack_message,
            input,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
