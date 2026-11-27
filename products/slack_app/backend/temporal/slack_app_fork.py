"""Forking a thread into a DM or into another channel.

Someone reading a thread wants to continue it somewhere else: dig into it in private
without turning the thread into their own tutorial, or move the work to the channel
where it belongs. The "…" menu under a reply posts a seed message in the clicker's DM,
or in the channel they pick, and starts a task in that message's thread at once.

The task gets a link to the forked thread, not a copy of it. The agent reads the
thread through the clicker's Slack MCP, with the clicker's own Slack access, and
continues from where it stopped. The run is the ordinary mention workflow: the
``fork_source_*`` inputs only change the task prompt. Everything downstream, from repo
selection to follow-ups, is the mention path untouched.
"""

import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.slack_app.backend.temporal.activities.fork import process_slack_app_fork_thread_activity
from products.slack_app.backend.temporal.types import SlackAppForkThreadInputs

SLACK_APP_FORK_TIMEOUT_SECONDS = 5 * 60


@workflow.defn(name="slack-app-fork-thread")
class SlackAppForkThreadWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SlackAppForkThreadInputs:
        loaded = json.loads(inputs[0])
        return SlackAppForkThreadInputs(**loaded)

    @workflow.run
    async def run(self, inputs: SlackAppForkThreadInputs) -> None:
        await workflow.execute_activity(
            process_slack_app_fork_thread_activity,
            args=(inputs,),
            start_to_close_timeout=timedelta(seconds=SLACK_APP_FORK_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
