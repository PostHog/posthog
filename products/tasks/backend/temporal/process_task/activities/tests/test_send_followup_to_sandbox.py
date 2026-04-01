import json

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox import (
    SendFollowupToSandboxInput,
    _get_stop_reason,
    _write_turn_complete,
    send_followup_to_sandbox,
)


class TestGetStopReason(BaseTest):
    def test_returns_result_stop_reason_when_present(self):
        self.assertEqual(_get_stop_reason({"result": {"stopReason": "max_tokens"}}), "max_tokens")

    def test_defaults_to_end_turn_when_missing(self):
        self.assertEqual(_get_stop_reason({"result": {}}), "end_turn")
        self.assertEqual(_get_stop_reason({}), "end_turn")
        self.assertEqual(_get_stop_reason(None), "end_turn")

    def test_defaults_to_end_turn_when_result_is_not_a_dict(self):
        self.assertEqual(_get_stop_reason({"result": "ok"}), "end_turn")


class TestWriteTurnComplete(BaseTest):
    @patch("products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.get_redis_connection")
    def test_writes_stop_reason_to_synthetic_event(self, mock_get_redis_connection):
        mock_conn = MagicMock()
        mock_get_redis_connection.return_value = mock_conn

        _write_turn_complete("run-123", "max_tokens")

        payload = mock_conn.xadd.call_args.args[1]["data"]
        event = json.loads(payload)
        self.assertEqual(event["notification"]["method"], "_posthog/turn_complete")
        self.assertEqual(event["notification"]["params"]["stopReason"], "max_tokens")


class TestSendFollowupToSandbox(BaseTest):
    @patch("products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.get_redis_connection")
    @patch("products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.send_user_message")
    @patch("products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.TaskRun.objects")
    def test_propagates_stop_reason_from_command_result(
        self, mock_task_run_objects, mock_send_user_message, mock_get_redis_connection
    ):
        task_run = MagicMock()
        task_run.task.created_by = None
        mock_task_run_objects.select_related.return_value.get.return_value = task_run
        mock_send_user_message.return_value = MagicMock(
            success=True,
            data={"result": {"stopReason": "max_tokens"}},
        )

        mock_conn = MagicMock()
        mock_get_redis_connection.return_value = mock_conn

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-123", message="hello"))

        payload = mock_conn.xadd.call_args.args[1]["data"]
        event = json.loads(payload)
        self.assertEqual(event["notification"]["params"]["stopReason"], "max_tokens")
