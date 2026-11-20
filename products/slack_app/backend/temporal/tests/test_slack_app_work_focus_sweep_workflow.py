import os
import uuid
from collections.abc import AsyncIterator

import pytest

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.slack_app.backend.temporal.slack_app_work_focus import (
    SlackAppDailyFocusSweepWorkflow,
    SlackAppWorkFocusWorkflow,
)
from products.slack_app.backend.temporal.types import SlackAppDailySummaryIndexInputs, SlackAppWorkFocusInputs


def _due(slack_team_id: str, slack_user_id: str) -> SlackAppWorkFocusInputs:
    return SlackAppWorkFocusInputs(
        integration_id=1 if slack_team_id == "T1" else 2,
        slack_team_id=slack_team_id,
        slack_user_id=slack_user_id,
        since=1_700_000_000,
        run_at=1_700_086_400,
    )


@pytest.fixture
async def env() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping(
        test_server_existing_path=os.environ.get("TEMPORAL_TEST_SERVER_PATH")
    ) as environment:
        yield environment


@pytest.mark.asyncio
async def test_each_workspace_is_indexed_once_before_its_people_run(env: WorkflowEnvironment) -> None:
    due = [_due("T1", "U1"), _due("T1", "U2"), _due("T2", "U3")]
    calls: list[str] = []

    @activity.defn(name="claim_due_slack_app_daily_focus_activity")
    async def claim() -> list[SlackAppWorkFocusInputs]:
        return due

    @activity.defn(name="index_slack_app_daily_summary_activity")
    async def index(inputs: SlackAppDailySummaryIndexInputs) -> int:
        calls.append(f"index:{inputs.slack_team_id}:{','.join(inputs.slack_user_ids)}")
        return 1

    @activity.defn(name="find_slack_app_work_focus_activity")
    async def find(inputs: SlackAppWorkFocusInputs) -> str:
        calls.append(f"find:{inputs.slack_team_id}:{inputs.slack_user_id}")
        return "sent"

    task_queue = str(uuid.uuid4())
    async with Worker(
        env.client,
        task_queue=task_queue,
        workflows=[SlackAppDailyFocusSweepWorkflow, SlackAppWorkFocusWorkflow],
        activities=[claim, index, find],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        started = await env.client.execute_workflow(
            SlackAppDailyFocusSweepWorkflow.run,
            id=f"slack-app-daily-focus-sweep-test-{uuid.uuid4()}",
            task_queue=task_queue,
        )
        # The children outlive the sweep; wait for each one's run to finish.
        for inputs in due:
            handle = env.client.get_workflow_handle(
                f"slack-app-daily-focus-{inputs.slack_team_id}-{inputs.slack_user_id}-{inputs.since}"
            )
            await handle.result()

    assert started == 3
    # One index per workspace, naming the people whose runs follow it, and no person runs before their index.
    assert sorted(call for call in calls if call.startswith("index:")) == ["index:T1:U1,U2", "index:T2:U3"]
    for team in ("T1", "T2"):
        index_at = calls.index(next(call for call in calls if call.startswith(f"index:{team}:")))
        assert all(calls.index(call) > index_at for call in calls if call.startswith(f"find:{team}:"))
