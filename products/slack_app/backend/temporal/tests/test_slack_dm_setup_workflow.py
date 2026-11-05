import os
import uuid
import asyncio
from collections.abc import AsyncIterator

import pytest

from temporalio import activity
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.slack_app.backend.temporal.slack_dm_setup import SlackDmSetupWorkflow
from products.slack_app.backend.temporal.types import (
    SlackDmSetupInputs,
    SlackDmSetupMessage,
    SlackDmSetupMessageInputs,
    SlackDmSetupPlan,
)

INPUTS = SlackDmSetupInputs(integration_id=1, slack_team_id="T1", slack_user_id="U1")


def _message(kind: str, ts: str | None = None) -> SlackDmSetupMessage:
    return SlackDmSetupMessage(kind=kind, text=kind, blocks=[], ts=ts)  # type: ignore[arg-type]


ROOT_PLAN = SlackDmSetupPlan(edits=[], post=_message("root"), finished=False, plan_again=True)
FIRST_STEP_PLAN = SlackDmSetupPlan(edits=[], post=_message("step"), finished=False, plan_again=False)
NEXT_STEP_PLAN = SlackDmSetupPlan(
    edits=[_message("step", ts="1"), _message("root", ts="0")], post=_message("step"), finished=False, plan_again=False
)
READY_PLAN = SlackDmSetupPlan(edits=[_message("root", ts="0")], post=_message("ready"), finished=True, plan_again=False)


class _Slack:
    """Fake activities. Plans come from a script, and each call is recorded as ``plan``, ``edit:<kind>``
    or ``post:<kind>``. ``failing_posts`` fails that many posts first."""

    def __init__(self, plans: list[SlackDmSetupPlan], failing_posts: int = 0) -> None:
        self.plans = plans
        self.failing_posts = failing_posts
        self.calls: list[str] = []
        self.refreshed = asyncio.Event()

    def activities(self) -> list:
        @activity.defn(name="plan_slack_dm_setup_activity")
        async def plan(_: SlackDmSetupInputs) -> SlackDmSetupPlan:
            self.calls.append("plan")
            return self.plans[min(self.calls.count("plan") - 1, len(self.plans) - 1)]

        @activity.defn(name="edit_slack_dm_setup_message_activity")
        async def edit(inputs: SlackDmSetupMessageInputs) -> None:
            self.calls.append(f"edit:{inputs.message.kind}")

        @activity.defn(name="post_slack_dm_setup_message_activity")
        async def post(inputs: SlackDmSetupMessageInputs) -> None:
            self.calls.append(f"post:{inputs.message.kind}")
            # A root post is followed by a step post in the same refresh, so only the step post ends it.
            if inputs.message.kind != "root":
                self.refreshed.set()
            if self.failing_posts:
                self.failing_posts -= 1
                raise ApplicationError("slack down")

        return [plan, edit, post]


@pytest.fixture
async def env() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping(
        test_server_existing_path=os.environ.get("TEMPORAL_TEST_SERVER_PATH")
    ) as environment:
        yield environment


async def _run(env: WorkflowEnvironment, slack: _Slack, *, refreshes: int) -> None:
    task_queue = str(uuid.uuid4())
    async with Worker(
        env.client,
        task_queue=task_queue,
        workflows=[SlackDmSetupWorkflow],
        activities=slack.activities(),
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        handle = await env.client.start_workflow(
            SlackDmSetupWorkflow.run,
            INPUTS,
            id=f"slack-dm-setup-test-{uuid.uuid4()}",
            task_queue=task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            start_signal="refresh",
        )
        for _ in range(refreshes):
            # Each refresh goes in after the previous one posted, so it plans against the new state.
            await asyncio.wait_for(slack.refreshed.wait(), timeout=10)
            slack.refreshed.clear()
            await handle.signal(SlackDmSetupWorkflow.refresh)
        await asyncio.wait_for(handle.result(), timeout=60)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plans, failing_posts, refreshes, expected_calls",
    [
        pytest.param(
            [ROOT_PLAN, FIRST_STEP_PLAN, NEXT_STEP_PLAN, READY_PLAN],
            0,
            2,
            [
                *["plan", "post:root", "plan", "post:step"],
                *["plan", "edit:step", "edit:root", "post:step"],
                *["plan", "edit:root", "post:ready"],
            ],
            id="each refresh plans, edits, then posts once, until ready ends the run",
        ),
        pytest.param(
            [FIRST_STEP_PLAN, READY_PLAN],
            1,
            1,
            ["plan", "post:step", "plan", "edit:root", "post:ready"],
            id="a failed post is not retried and the next refresh plans again",
        ),
        pytest.param(
            [FIRST_STEP_PLAN],
            0,
            0,
            ["plan", "post:step"],
            id="without a refresh for a week the run ends",
        ),
    ],
)
async def test_workflow_applies_one_plan_per_refresh(
    env: WorkflowEnvironment,
    plans: list[SlackDmSetupPlan],
    failing_posts: int,
    refreshes: int,
    expected_calls: list[str],
) -> None:
    slack = _Slack(plans, failing_posts=failing_posts)

    await _run(env, slack, refreshes=refreshes)

    assert slack.calls == expected_calls
