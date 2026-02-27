import importlib
from types import SimpleNamespace

from unittest.mock import patch

from django.apps import apps
from django.test import TestCase

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

_module = importlib.import_module("products.tasks.backend.temporal.process_task.activities.forward_pending_message")
forward_pending_user_message = _module.forward_pending_user_message


def _command_result(**kwargs):
    defaults = {"success": False, "status_code": 0, "error": None, "retryable": False, "data": None}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestForwardPendingUserMessage(TestCase):
    def setUp(self):
        self.Task = apps.get_model("tasks", "Task")
        self.TaskRun = apps.get_model("tasks", "TaskRun")
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        self.task = self.Task.objects.create(
            team=self.team,
            title="Test task",
            description="desc",
            origin_product=self.Task.OriginProduct.SLACK,
            created_by=self.user,
            repository="org/repo",
        )

    def _make_run(self, state=None):
        return self.TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=self.TaskRun.Status.IN_PROGRESS,
            state=state or {},
        )

    def test_no_pending_message_is_noop(self):
        run = self._make_run(state={"mode": "background"})
        forward_pending_user_message(str(run.id))
        run.refresh_from_db()
        assert run.state == {"mode": "background"}

    @patch("products.tasks.backend.services.connection_token.create_sandbox_connection_token", return_value="jwt")
    @patch("products.tasks.backend.services.agent_command.send_user_message")
    def test_pending_message_delivered_successfully(self, mock_send, mock_token):
        run = self._make_run(
            state={
                "pending_user_message": "fix the tests",
                "sandbox_url": "https://sandbox.example.com/rpc",
            }
        )
        mock_send.return_value = _command_result(success=True, status_code=200)

        forward_pending_user_message(str(run.id))

        mock_send.assert_called_once()
        assert mock_send.call_args[0][1] == "fix the tests"
        run.refresh_from_db()
        assert "pending_user_message" not in run.state

    @patch("products.tasks.backend.services.connection_token.create_sandbox_connection_token", return_value="jwt")
    @patch("products.tasks.backend.services.agent_command.send_user_message")
    def test_retryable_failure_keeps_message_in_state(self, mock_send, mock_token):
        run = self._make_run(
            state={
                "pending_user_message": "fix the tests",
                "sandbox_url": "https://sandbox.example.com/rpc",
            }
        )
        mock_send.return_value = _command_result(success=False, status_code=504, error="timeout", retryable=True)

        forward_pending_user_message(str(run.id))

        assert mock_send.call_count == 2
        run.refresh_from_db()
        assert run.state.get("pending_user_message") == "fix the tests"

    @patch("products.tasks.backend.services.connection_token.create_sandbox_connection_token", return_value="jwt")
    @patch("products.tasks.backend.services.agent_command.send_user_message")
    def test_non_retryable_failure_clears_message_from_state(self, mock_send, mock_token):
        run = self._make_run(
            state={
                "pending_user_message": "fix the tests",
                "sandbox_url": "https://sandbox.example.com/rpc",
            }
        )
        mock_send.return_value = _command_result(success=False, status_code=401, error="Unauthorized", retryable=False)

        forward_pending_user_message(str(run.id))

        mock_send.assert_called_once()
        run.refresh_from_db()
        assert "pending_user_message" not in run.state
