from pathlib import Path

import pytest

from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner

from products.slack_app.backend.temporal.slack_app_mention import SlackAppMentionWorkflow


@pytest.mark.asyncio
async def test_queue_run_recorded_with_the_rename_patch_replays() -> None:
    history = WorkflowHistory.from_json(
        "slack-app-mention-replay",
        (Path(__file__).parent / "histories" / "mention_queue_with_rename_patch.json").read_text(),
    )
    child_types = [
        event.start_child_workflow_execution_initiated_event_attributes.workflow_type.name
        for event in history.events
        if event.event_type == EventType.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED
    ]
    assert child_types == ["slack-app-mention-processing"]

    await Replayer(
        workflows=[SlackAppMentionWorkflow],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ).replay_workflow(history)
