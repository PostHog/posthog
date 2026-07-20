from unittest.mock import AsyncMock, MagicMock, patch

from products.tasks.backend.temporal.client import (
    execute_posthog_code_agent_relay_workflow,
    signal_task_followup_message,
)
from products.tasks.backend.temporal.slack_relay.activities import RelaySlackMessageInput


@patch("products.tasks.backend.temporal.client.sync_connect")
def test_relay_enqueue_constructs_workflow_input(mock_connect: MagicMock) -> None:
    # Guards against the client kwargs drifting from the RelaySlackMessageInput
    # fields — that mismatch raises TypeError at enqueue time and every Slack
    # relay surfaces as a 503 while the sandbox swallows the error silently.
    mock_client = MagicMock(start_workflow=AsyncMock())
    mock_connect.return_value = mock_client

    relay_id = execute_posthog_code_agent_relay_workflow(
        run_id="run-1", text="hello", relay_id="relay-1", user_message_ts="123.456"
    )

    assert relay_id == "relay-1"
    workflow_input = mock_client.start_workflow.call_args.args[1]
    assert isinstance(workflow_input, RelaySlackMessageInput)
    assert workflow_input.text == "hello"
    assert workflow_input.run_id == "run-1"


@patch("products.tasks.backend.temporal.client.sync_connect")
def test_followup_signal_sends_expected_args(mock_connect: MagicMock) -> None:
    handle = MagicMock(signal=AsyncMock())
    mock_connect.return_value = MagicMock(get_workflow_handle=MagicMock(return_value=handle))

    signal_task_followup_message("wf-1", "hi", ["artifact-1"], message_id="msg-1")

    handle.signal.assert_awaited_once_with("send_followup_message", args=["hi", ["artifact-1"], "msg-1"])
