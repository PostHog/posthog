import json
from types import SimpleNamespace

from unittest.mock import MagicMock, patch

from django.apps import apps
from django.test import TestCase

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.tasks import process_twig_task_termination


def _command_result(**kwargs):
    defaults = {"success": False, "status_code": 0, "error": None, "retryable": False}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestProcessTwigTaskTermination(TestCase):
    def setUp(self):
        self.Task = apps.get_model("tasks", "Task")
        self.TaskRun = apps.get_model("tasks", "TaskRun")
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        self.integration = Integration.objects.create(
            team=self.team, kind="slack-twig", integration_id="T_SLACK", config={}
        )
        self.task = self.Task.objects.create(
            team=self.team,
            title="Test task",
            description="desc",
            origin_product=self.Task.OriginProduct.SLACK,
            created_by=self.user,
            repository="org/repo",
        )
        self.task_run = self.TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=self.TaskRun.Status.IN_PROGRESS,
            state={"sandbox_url": "https://sandbox.example.com/rpc"},
        )

    def _make_payload(self, run_id: str | None = None, user_id: str = "U_ALICE") -> dict:
        value = json.dumps(
            {
                "run_id": run_id or str(self.task_run.id),
                "integration_id": self.integration.id,
                "mentioning_slack_user_id": user_id,
                "thread_ts": "1234.5678",
            }
        )
        return {
            "type": "block_actions",
            "actions": [{"action_id": "twig_terminate_task", "value": value, "action_ts": "1234567890.123"}],
            "user": {"id": user_id},
            "team": {"id": "T_SLACK"},
            "channel": {"id": "C123"},
            "message": {"ts": "1234.5678", "thread_ts": "1234.5678"},
        }

    @patch("products.tasks.backend.services.connection_token.create_sandbox_connection_token", return_value="jwt-token")
    @patch("products.tasks.backend.services.agent_command.send_cancel")
    @patch("posthog.temporal.common.client.sync_connect")
    def test_command_dispatched_on_success(self, mock_sync_connect, mock_send_cancel, mock_token):
        mock_send_cancel.return_value = _command_result(success=True, status_code=200)
        mock_handle = MagicMock()
        mock_client = MagicMock()
        mock_client.get_workflow_handle.return_value = mock_handle
        mock_sync_connect.return_value = mock_client
        payload = self._make_payload()

        with patch("posthog.models.integration.SlackIntegration"):
            process_twig_task_termination(payload)

        mock_token.assert_called_once()
        mock_send_cancel.assert_called_once_with(self.task_run, auth_token="jwt-token")
        mock_handle.signal.assert_called_once()

    @patch("products.tasks.backend.services.connection_token.create_sandbox_connection_token", return_value="jwt-token")
    @patch("posthog.temporal.common.client.sync_connect")
    @patch("products.tasks.backend.services.agent_command.send_cancel")
    def test_fallback_signal_on_connection_error(self, mock_send_cancel, mock_sync_connect, mock_token):
        mock_send_cancel.return_value = _command_result(
            success=False, status_code=502, error="Connection refused", retryable=True
        )
        mock_handle = MagicMock()
        mock_client = MagicMock()
        mock_client.get_workflow_handle.return_value = mock_handle
        mock_sync_connect.return_value = mock_client

        payload = self._make_payload()
        with patch("posthog.models.integration.SlackIntegration"):
            process_twig_task_termination(payload)

        mock_send_cancel.assert_called_once_with(self.task_run, auth_token="jwt-token")
        mock_handle.signal.assert_called_once()

    @patch("products.tasks.backend.services.connection_token.create_sandbox_connection_token", return_value="jwt-token")
    @patch("products.tasks.backend.services.agent_command.send_cancel")
    def test_still_signals_on_4xx(self, mock_send_cancel, mock_token):
        mock_send_cancel.return_value = _command_result(
            success=False, status_code=401, error="Unauthorized", retryable=False
        )
        payload = self._make_payload()
        # Should still signal workflow to guarantee cleanup path
        with patch("posthog.temporal.common.client.sync_connect") as mock_sync_connect:
            mock_handle = MagicMock()
            mock_client = MagicMock()
            mock_client.get_workflow_handle.return_value = mock_handle
            mock_sync_connect.return_value = mock_client
            process_twig_task_termination(payload)
            mock_send_cancel.assert_called_once_with(self.task_run, auth_token="jwt-token")
            mock_sync_connect.assert_called_once()
            mock_handle.signal.assert_called_once()

    def test_user_mismatch_rejected(self):
        payload = self._make_payload(user_id="U_ALICE")
        payload["user"]["id"] = "U_BOB"
        # Should return early without any command or signal
        with patch("products.tasks.backend.services.agent_command.send_cancel") as mock_send:
            process_twig_task_termination(payload)
            mock_send.assert_not_called()

    @patch("posthog.models.integration.SlackIntegration")
    def test_terminal_run_posts_feedback(self, mock_slack_cls):
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.save()
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        payload = self._make_payload()
        process_twig_task_termination(payload)

        mock_slack_instance.client.chat_postMessage.assert_called_once()
        call_kwargs = mock_slack_instance.client.chat_postMessage.call_args.kwargs
        assert "already" in call_kwargs["text"]
