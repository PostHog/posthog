import os
import uuid
import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta

import pytest

from temporalio import activity
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.slack_app.backend.temporal.slack_app_onboarding import SlackAppOnboardingWorkflow
from products.slack_app.backend.temporal.types import (
    SlackAppOnboardingInputs,
    SlackAppOnboardingMessage,
    SlackAppOnboardingMessageInputs,
    SlackAppOnboardingPlan,
)

INPUTS = SlackAppOnboardingInputs(integration_id=1, slack_team_id="T1", slack_user_id="U1")


def _message(kind: str, ts: str | None = None) -> SlackAppOnboardingMessage:
    return SlackAppOnboardingMessage(
        kind=kind,  # type: ignore[arg-type]
        text=kind,
        blocks=[],
        ts=ts,
        step="model" if kind == "step" else None,
        progress="1 of 3 steps done" if kind == "root" else None,
        summarizes_step=kind == "step" and ts is not None,
    )


ROOT_PLAN = SlackAppOnboardingPlan(edits=[], post=_message("root"), finished=False)
FIRST_STEP_PLAN = SlackAppOnboardingPlan(edits=[], post=_message("step"), finished=False)
NEXT_STEP_PLAN = SlackAppOnboardingPlan(
    edits=[_message("step", ts="1"), _message("root", ts="0")], post=_message("step"), finished=False
)
READY_PLAN = SlackAppOnboardingPlan(edits=[_message("root", ts="0")], post=_message("ready"), finished=True)


class _Slack:
    def __init__(self, plans: list[SlackAppOnboardingPlan], failing_posts: int = 0) -> None:
        self.plans = plans
        self.failing_posts = failing_posts
        self.calls: list[str] = []
        self.refreshed = asyncio.Event()

    def activities(self) -> list:
        @activity.defn(name="plan_slack_app_onboarding_activity")
        async def plan(_: SlackAppOnboardingInputs) -> SlackAppOnboardingPlan:
            self.calls.append("plan")
            return self.plans[min(self.calls.count("plan") - 1, len(self.plans) - 1)]

        @activity.defn(name="edit_slack_app_onboarding_message_activity")
        async def edit(inputs: SlackAppOnboardingMessageInputs) -> None:
            self.calls.append(f"edit:{inputs.message.kind}")

        @activity.defn(name="post_slack_app_onboarding_message_activity")
        async def post(inputs: SlackAppOnboardingMessageInputs) -> None:
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


async def _run(
    env: WorkflowEnvironment, slack: _Slack, *, refreshes: int, inputs: SlackAppOnboardingInputs = INPUTS
) -> list[str]:
    task_queue = str(uuid.uuid4())
    async with Worker(
        env.client,
        task_queue=task_queue,
        workflows=[SlackAppOnboardingWorkflow],
        activities=slack.activities(),
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        handle = await env.client.start_workflow(
            SlackAppOnboardingWorkflow.run,
            inputs,
            id=f"slack-app-onboarding-test-{uuid.uuid4()}",
            task_queue=task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            start_signal="refresh",
        )
        for _ in range(refreshes):
            # Each refresh goes in after the previous one posted, so it plans against the new state.
            await asyncio.wait_for(slack.refreshed.wait(), timeout=10)
            slack.refreshed.clear()
            await handle.signal(SlackAppOnboardingWorkflow.refresh)
        await asyncio.wait_for(handle.result(), timeout=60)
        summaries: list[str] = []
        async for event in handle.fetch_history_events():
            if event.HasField("activity_task_scheduled_event_attributes") and event.HasField("user_metadata"):
                summary = env.client.data_converter.payload_converter.from_payload(event.user_metadata.summary, str)
                summaries.append(summary)
        return summaries


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
    plans: list[SlackAppOnboardingPlan],
    failing_posts: int,
    refreshes: int,
    expected_calls: list[str],
) -> None:
    slack = _Slack(plans, failing_posts=failing_posts)

    summaries = await _run(env, slack, refreshes=refreshes)

    assert slack.calls == expected_calls
    assert len(summaries) == len(expected_calls)


@pytest.mark.asyncio
async def test_each_activity_names_the_message_it_sends_in_the_history(env: WorkflowEnvironment) -> None:
    slack = _Slack([ROOT_PLAN, FIRST_STEP_PLAN, NEXT_STEP_PLAN, READY_PLAN])

    summaries = await _run(env, slack, refreshes=2)

    assert summaries == [
        *["plan", "post top message: 1 of 3 steps done", "plan", "post model: show step"],
        *["plan", "edit model: shrink to one line", "edit top message: 1 of 3 steps done", "post model: show step"],
        *["plan", "edit top message: 1 of 3 steps done", "post ready message"],
    ]


@pytest.mark.asyncio
async def test_a_delayed_start_waits_before_its_first_plan(env: WorkflowEnvironment) -> None:
    slack = _Slack([FIRST_STEP_PLAN])
    delayed = replace(INPUTS, start_delay_seconds=300)

    started_at = await env.get_current_time()
    summaries = await _run(env, slack, refreshes=0, inputs=delayed)

    assert slack.calls == ["plan", "post:step"]
    assert summaries == ["plan", "post model: show step"]
    assert await env.get_current_time() - started_at >= timedelta(seconds=300)
