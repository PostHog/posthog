from pathlib import Path

import pytest

from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner

from products.logs.backend.temporal.workflow import LogsAlertCheckWorkflow


@pytest.fixture(params=["unbounded_before_patch", "bounded_cap_2"])
def history(request: pytest.FixtureRequest) -> WorkflowHistory:
    return WorkflowHistory.from_json(
        "logs-alert-check-replay", (Path(__file__).parent / "histories" / f"{request.param}.json").read_text()
    )


@pytest.mark.asyncio
async def test_saved_history_replays(history: WorkflowHistory) -> None:
    await Replayer(workflows=[LogsAlertCheckWorkflow], workflow_runner=UnsandboxedWorkflowRunner()).replay_workflow(
        history
    )
