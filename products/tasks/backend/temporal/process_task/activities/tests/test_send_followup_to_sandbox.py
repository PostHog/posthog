import json
from types import SimpleNamespace
from typing import ClassVar

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import TestCase

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.tasks.backend.facade import api as facade
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox import (
    SendFollowupToSandboxInput,
    _get_stop_reason,
    _write_turn_complete,
    send_followup_to_sandbox,
)

_MODULE = "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox"


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
    @patch(
        "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.get_tasks_stream_redis_sync"
    )
    def test_writes_stop_reason_to_synthetic_event(self, mock_get_tasks_stream_redis_sync):
        mock_conn = MagicMock()
        mock_get_tasks_stream_redis_sync.return_value = mock_conn

        _write_turn_complete("run-123", "max_tokens")

        payload = mock_conn.xadd.call_args.args[1]["data"]
        event = json.loads(payload)
        self.assertEqual(event["notification"]["method"], "_posthog/turn_complete")
        self.assertEqual(event["notification"]["params"]["stopReason"], "max_tokens")


class TestSendFollowupToSandbox(BaseTest):
    @patch(
        "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.get_tasks_stream_redis_sync"
    )
    @patch("products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.send_user_message")
    @patch("products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.TaskRun.objects")
    def test_propagates_stop_reason_from_command_result(
        self, mock_task_run_objects, mock_send_user_message, mock_get_tasks_stream_redis_sync
    ):
        task_run = MagicMock()
        task_run.task.created_by = None
        mock_task_run_objects.select_related.return_value.get.return_value = task_run
        mock_send_user_message.return_value = MagicMock(
            success=True,
            data={"result": {"stopReason": "max_tokens"}},
        )

        mock_conn = MagicMock()
        mock_get_tasks_stream_redis_sync.return_value = mock_conn

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-123", message="hello"))

        payload = mock_conn.xadd.call_args.args[1]["data"]
        event = json.loads(payload)
        self.assertEqual(event["notification"]["params"]["stopReason"], "max_tokens")


@patch(f"{_MODULE}._refresh_sandbox_mcp")
@patch(f"{_MODULE}.create_sandbox_connection_token", return_value="jwt")
@patch(f"{_MODULE}.get_tasks_stream_redis_sync")
@patch(f"{_MODULE}.send_user_message")
class TestSendFollowupPersonalInstructions(TestCase):
    org: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Org")
        cls.team = Team.objects.create(organization=cls.org, name="Team")
        cls.user = User.objects.create(email="actor@test.com", distinct_id="actor")

    def _run_with_instructions(self, content: str, state: dict) -> TaskRun:
        facade.get_code_custom_instructions(self.team.id, self.user.id)
        facade.save_code_custom_instructions(self.team.id, self.user.id, content=content, expected_version=1)
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
        )
        return TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS, state=state)

    def test_turn_in_flight_first_message_injects_and_marks(self, mock_send, mock_redis, mock_token, mock_refresh):
        run = self._run_with_instructions("Prefer tabs.", state={"sandbox_url": "https://s.example/rpc"})
        mock_send.return_value = SimpleNamespace(
            success=False, turn_in_flight=True, status_code=0, error=None, data=None, retryable=False
        )

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id=str(run.id), message="do the work"))

        delivered = mock_send.call_args[0][1]
        assert "<user_custom_instructions>" in delivered
        assert delivered.endswith("do the work")
        run.refresh_from_db()
        assert run.state.get("personal_instructions_applied") is True

    def test_already_applied_run_delivers_plain(self, mock_send, mock_redis, mock_token, mock_refresh):
        run = self._run_with_instructions(
            "Prefer tabs.", state={"personal_instructions_applied": True, "sandbox_url": "https://s.example/rpc"}
        )
        mock_send.return_value = SimpleNamespace(
            success=True, turn_in_flight=False, status_code=200, error=None, data={"result": {}}, retryable=False
        )

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id=str(run.id), message="second turn"))

        assert mock_send.call_args[0][1] == "second turn"
