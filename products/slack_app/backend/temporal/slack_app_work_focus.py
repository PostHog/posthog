import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.slack_app.backend.temporal.activities.slack_app_work_focus import find_slack_app_work_focus_activity
from products.slack_app.backend.temporal.types import SlackAppWorkFocusInputs

SLACK_APP_WORK_FOCUS_ACTIVITY_TIMEOUT = timedelta(minutes=2)
# A burst of links runs out of search calls for the workspace. The retries wait for tokens, a minute apart at first.
_RETRY = RetryPolicy(initial_interval=timedelta(minutes=1), backoff_coefficient=2.0, maximum_attempts=5)


def slack_app_work_focus_workflow_id(slack_team_id: str, slack_user_id: str) -> str:
    return f"slack-app-work-focus-{slack_team_id}-{slack_user_id}"


@workflow.defn(name="slack-app-work-focus")
class SlackAppWorkFocusWorkflow(PostHogWorkflow):
    """One run per person after the account link. The search, the model call and the DM run in one activity,
    so the messages never pass through Temporal."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SlackAppWorkFocusInputs:
        return SlackAppWorkFocusInputs(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, inputs: SlackAppWorkFocusInputs) -> None:
        outcome = await workflow.execute_activity(
            find_slack_app_work_focus_activity,
            inputs,
            start_to_close_timeout=SLACK_APP_WORK_FOCUS_ACTIVITY_TIMEOUT,
            retry_policy=_RETRY,
            summary="find the work focus",
        )
        workflow.set_current_details(outcome)
