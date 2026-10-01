from pathlib import Path

import pytest

from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner

from products.logs.backend.temporal.workflow import LogsAlertCheckWorkflow


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["unbounded_before_patch", "bounded_cap_2"])
async def test_saved_history_replays(name: str) -> None:
    history = WorkflowHistory.from_json(
        "logs-alert-check-replay", (Path(__file__).parent / "histories" / f"{name}.json").read_text()
    )
    await Replayer(workflows=[LogsAlertCheckWorkflow], workflow_runner=UnsandboxedWorkflowRunner()).replay_workflow(
        history
    )
