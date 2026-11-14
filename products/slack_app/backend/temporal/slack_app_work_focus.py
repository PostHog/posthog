import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.base import PostHogWorkflow

from products.slack_app.backend.temporal.activities.slack_app_work_focus import (
    claim_due_slack_app_daily_focus_activity,
    find_slack_app_work_focus_activity,
)
from products.slack_app.backend.temporal.types import SlackAppWorkFocusInputs

SLACK_APP_WORK_FOCUS_ACTIVITY_TIMEOUT = timedelta(minutes=2)
# A burst of links runs out of search calls for the workspace. The retries wait for tokens, a minute apart at first.
_RETRY = RetryPolicy(initial_interval=timedelta(minutes=1), backoff_coefficient=2.0, maximum_attempts=5)
# Everyone in a timezone runs at about the same time, so a large workspace waits longer for search calls.
_DAILY_RETRY = RetryPolicy(
    initial_interval=timedelta(minutes=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=10),
    maximum_attempts=12,
)


def slack_app_work_focus_workflow_id(slack_team_id: str, slack_user_id: str) -> str:
    return f"slack-app-work-focus-{slack_team_id}-{slack_user_id}"


def slack_app_daily_focus_workflow_id(inputs: SlackAppWorkFocusInputs) -> str:
    return f"slack-app-daily-focus-{inputs.slack_team_id}-{inputs.slack_user_id}-{inputs.since}"


@workflow.defn(name="slack-app-work-focus")
class SlackAppWorkFocusWorkflow(PostHogWorkflow):
    """One run per person after the account link. The search, the model call and the DM run in one activity,
    so the messages never pass through Temporal."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SlackAppWorkFocusInputs:
        return SlackAppWorkFocusInputs(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, inputs: SlackAppWorkFocusInputs) -> None:
        if inputs.start_delay_seconds > 0:
            await workflow.sleep(timedelta(seconds=inputs.start_delay_seconds))
        outcome = await workflow.execute_activity(
            find_slack_app_work_focus_activity,
            inputs,
            start_to_close_timeout=SLACK_APP_WORK_FOCUS_ACTIVITY_TIMEOUT,
            retry_policy=_RETRY if inputs.since is None else _DAILY_RETRY,
            summary="find the work focus",
        )
        workflow.set_current_details(outcome)


@workflow.defn(name="slack-app-daily-focus-sweep")
class SlackAppDailyFocusSweepWorkflow(PostHogWorkflow):
    """Runs every 15 minutes and starts a daily work focus for each person whose time has come."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @workflow.run
    async def run(self) -> int:
        due = await workflow.execute_activity(
            claim_due_slack_app_daily_focus_activity,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
            summary="claim the due daily work focus runs",
        )
        started = 0
        for inputs in due:
            try:
                await workflow.start_child_workflow(
                    SlackAppWorkFocusWorkflow.run,
                    inputs,
                    id=slack_app_daily_focus_workflow_id(inputs),
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                )
                started += 1
            except WorkflowAlreadyStartedError:
                pass
        return started
