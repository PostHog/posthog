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
from products.slack_app.backend.temporal.types import SlackDmSetupInputs

INPUTS = SlackDmSetupInputs(integration_id=1, slack_team_id="T1", slack_user_id="U1")


class _Renders:
    """Answers each render with the next scripted outcome: True ends the setup, False keeps it open,
    and an exception fails that render."""

    def __init__(self, outcomes: list[bool | Exception]) -> None:
        self.outcomes = outcomes
        self.count = 0
        self.rendered = asyncio.Event()

    def activity(self):
        @activity.defn(name="render_slack_dm_setup_card_activity")
        async def render(_: SlackDmSetupInputs) -> bool:
            outcome = self.outcomes[min(self.count, len(self.outcomes) - 1)]
            self.count += 1
            self.rendered.set()
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return render


@pytest.fixture
async def env() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping(
        test_server_existing_path=os.environ.get("TEMPORAL_TEST_SERVER_PATH")
    ) as environment:
        yield environment


async def _run(env: WorkflowEnvironment, renders: _Renders, *, signals_after_first_render: int) -> None:
    task_queue = str(uuid.uuid4())
    async with Worker(
        env.client,
        task_queue=task_queue,
        workflows=[SlackDmSetupWorkflow],
        activities=[renders.activity()],
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
        for _ in range(signals_after_first_render):
            await asyncio.wait_for(renders.rendered.wait(), timeout=10)
            renders.rendered.clear()
            await handle.signal(SlackDmSetupWorkflow.refresh)
        await handle.result()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcomes, signals_after_first_render, expected_renders",
    [
        # A refresh renders again, and the render that finds the setup done ends the run.
        ([False, True], 1, 2),
        # A failed render does not end the run, so the next refresh still renders.
        ([ApplicationError("slack down", non_retryable=True), True], 1, 2),
        # With no refresh for a week, the run ends after its first render.
        ([False], 0, 1),
    ],
)
async def test_workflow_renders_once_per_refresh_until_the_setup_ends(
    env: WorkflowEnvironment,
    outcomes: list[bool | Exception],
    signals_after_first_render: int,
    expected_renders: int,
) -> None:
    renders = _Renders(outcomes)

    await asyncio.wait_for(_run(env, renders, signals_after_first_render=signals_after_first_render), timeout=60)

    assert renders.count == expected_renders
