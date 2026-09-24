from pathlib import Path

import pytest

from django.test import override_settings

from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner

from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow


@pytest.fixture(params=["turn_ended_before_patch", "continued_open_turn"])
def history(request: pytest.FixtureRequest) -> WorkflowHistory:
    return WorkflowHistory.from_json(
        "process-task-replay", (Path(__file__).parent / "histories" / f"{request.param}.json").read_text()
    )


@pytest.mark.asyncio
@override_settings(TASKS_INACTIVITY_TIMEOUT_SECONDS=0)
async def test_saved_history_replays(history: WorkflowHistory) -> None:
    await Replayer(
        workflows=[ProcessTaskWorkflow],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ).replay_workflow(history)
