from pathlib import Path

import pytest

from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner

from products.slack_app.backend.temporal.slack_app_mention import SlackAppMentionWorkflow

HISTORIES = sorted((Path(__file__).parent / "histories").glob("*.json"))


@pytest.fixture(params=HISTORIES, ids=[path.stem for path in HISTORIES])
def history(request: pytest.FixtureRequest) -> WorkflowHistory:
    return WorkflowHistory.from_json("slack-app-mention-replay", request.param.read_text())


@pytest.mark.asyncio
async def test_saved_history_replays(history: WorkflowHistory) -> None:
    await Replayer(
        workflows=[SlackAppMentionWorkflow],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ).replay_workflow(history)
