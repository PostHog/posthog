import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow

from products.slack_app.backend.temporal.activities.dm_setup import (
    edit_slack_dm_setup_message_activity,
    plan_slack_dm_setup_activity,
    post_slack_dm_setup_message_activity,
)
from products.slack_app.backend.temporal.types import SlackDmSetupInputs, SlackDmSetupMessageInputs

SLACK_DM_SETUP_IDLE_TIMEOUT = timedelta(days=7)
SLACK_DM_SETUP_ACTIVITY_TIMEOUT = timedelta(seconds=60)
# A refresh needs at most two plans: one to post the top message, one to post the first step under it.
SLACK_DM_SETUP_MAX_PLANS_PER_REFRESH = 3
# Plans and edits can run again safely. A post cannot: a retry after a post could send the message twice.
_SAFE_TO_RETRY = RetryPolicy(maximum_attempts=3)
_ONE_ATTEMPT = RetryPolicy(maximum_attempts=1)


def slack_dm_setup_workflow_id(slack_team_id: str, slack_user_id: str) -> str:
    return f"slack-dm-setup-{slack_team_id}-{slack_user_id}"


@workflow.defn(name="posthog-slack-dm-setup")
class SlackDmSetupWorkflow(PostHogWorkflow):
    """One run per person keeps their DM setup thread up to date.

    The webhook, the account link and the setup buttons only save their change and send ``refresh``.
    For each refresh this workflow runs the same commands: a plan activity, then the edits the plan
    lists, then at most one post. The plan decides everything from the database, so adding or
    reordering setup steps changes no workflow command and needs no ``workflow.patched``.
    The run ends when the setup is done, or after a week without a ``refresh``.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SlackDmSetupInputs:
        return SlackDmSetupInputs(**json.loads(inputs[0]))

    @workflow.init
    def __init__(self, inputs: SlackDmSetupInputs) -> None:
        # The first render needs no signal. Set here and not in run(), because buffered signals run first.
        self._render_requested = True

    @workflow.signal
    async def refresh(self) -> None:
        self._render_requested = True

    async def _render(self, inputs: SlackDmSetupInputs) -> bool:
        """Apply the plans for one refresh. Returns True when the setup is finished."""
        for _ in range(SLACK_DM_SETUP_MAX_PLANS_PER_REFRESH):
            plan = await workflow.execute_activity(
                plan_slack_dm_setup_activity,
                inputs,
                start_to_close_timeout=SLACK_DM_SETUP_ACTIVITY_TIMEOUT,
                retry_policy=_SAFE_TO_RETRY,
            )
            for edit in plan.edits:
                await workflow.execute_activity(
                    edit_slack_dm_setup_message_activity,
                    SlackDmSetupMessageInputs(setup=inputs, message=edit),
                    start_to_close_timeout=SLACK_DM_SETUP_ACTIVITY_TIMEOUT,
                    retry_policy=_SAFE_TO_RETRY,
                )
            if plan.post is not None:
                await workflow.execute_activity(
                    post_slack_dm_setup_message_activity,
                    SlackDmSetupMessageInputs(setup=inputs, message=plan.post),
                    start_to_close_timeout=SLACK_DM_SETUP_ACTIVITY_TIMEOUT,
                    retry_policy=_ONE_ATTEMPT,
                )
            if not plan.plan_again:
                return plan.finished
        return False

    @workflow.run
    async def run(self, inputs: SlackDmSetupInputs) -> None:
        while True:
            try:
                await workflow.wait_condition(lambda: self._render_requested, timeout=SLACK_DM_SETUP_IDLE_TIMEOUT)
            except TimeoutError:
                # A refresh that lands between the timeout and the return must not be dropped.
                await workflow.wait_condition(workflow.all_handlers_finished)
                if self._render_requested:
                    continue
                return

            self._render_requested = False
            try:
                finished = await self._render(inputs)
            except ActivityError:
                # The next refresh plans again from the database, so a failed step is not lost.
                workflow.logger.warning(
                    "slack_app_dm_setup_render_failed", extra={"slack_user_id": inputs.slack_user_id}
                )
                continue

            if finished:
                await workflow.wait_condition(workflow.all_handlers_finished)
                return

            if workflow.info().is_continue_as_new_suggested():
                await workflow.wait_condition(workflow.all_handlers_finished)
                workflow.continue_as_new(inputs)
