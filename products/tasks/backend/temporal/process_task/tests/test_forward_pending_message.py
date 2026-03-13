import importlib
from types import SimpleNamespace

from unittest.mock import patch

from django.apps import apps
from django.test import TestCase

from posthog.models.integration import Integration
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
        self.slack_integration = Integration.objects.create(
            team=self.team,
            kind="slack-posthog-code",
            integration_id="T123",
            config={},
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
    def test_timeout_skips_retry_to_avoid_duplicate_delivery(self, mock_send, mock_token):
        run = self._make_run(
            state={
                "pending_user_message": "fix the tests",
                "sandbox_url": "https://sandbox.example.com/rpc",
            }
        )
        mock_send.return_value = _command_result(success=False, status_code=504, error="timeout", retryable=True)

        forward_pending_user_message(str(run.id))

        mock_send.assert_called_once()
        run.refresh_from_db()
        assert run.state.get("pending_user_message") == "fix the tests"

    @patch("products.tasks.backend.services.connection_token.create_sandbox_connection_token", return_value="jwt")
    @patch("products.tasks.backend.services.agent_command.send_user_message")
    def test_connection_error_retries_with_longer_timeout(self, mock_send, mock_token):
        run = self._make_run(
            state={
                "pending_user_message": "fix the tests",
                "sandbox_url": "https://sandbox.example.com/rpc",
            }
        )
        mock_send.return_value = _command_result(
            success=False, status_code=502, error="connection failed", retryable=True
        )

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

    @patch("products.tasks.backend.temporal.client.execute_posthog_code_agent_relay_workflow")
    @patch("products.tasks.backend.services.connection_token.create_sandbox_connection_token", return_value="jwt")
    @patch("products.tasks.backend.services.agent_command.send_user_message")
    def test_slack_origin_posts_reply_and_cleans_progress(
        self,
        mock_send,
        mock_token,
        mock_enqueue_relay,
    ):
        run = self._make_run(
            state={
                "pending_user_message": "fix the tests",
                "pending_user_message_ts": "1234.5",
                "interaction_origin": "slack",
                "sandbox_url": "https://sandbox.example.com/rpc",
            }
        )
        self.SlackThreadTaskMapping = apps.get_model("slack_app", "SlackThreadTaskMapping")
        self.SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.slack_integration,
            slack_workspace_id="T123",
            channel="C123",
            thread_ts="1111.1",
            task=self.task,
            task_run=run,
            mentioning_slack_user_id="U123",
        )

        mock_send.return_value = _command_result(
            success=True,
            status_code=200,
            data={"result": {"assistant_message": "Which license should I use?"}},
        )

        forward_pending_user_message(str(run.id))

        mock_enqueue_relay.assert_called_once_with(
            run_id=str(run.id),
            text="Which license should I use?",
            user_message_ts="1234.5",
        )
        run.refresh_from_db()
        assert "pending_user_message" not in run.state
        assert "pending_user_message_ts" not in run.state

    @patch("products.tasks.backend.temporal.client.execute_posthog_code_agent_relay_workflow")
    @patch("products.tasks.backend.services.connection_token.create_sandbox_connection_token", return_value="jwt")
    @patch("products.tasks.backend.services.agent_command.send_user_message")
    def test_slack_origin_non_retryable_failure_posts_error(
        self,
        mock_send,
        mock_token,
        mock_enqueue_relay,
    ):
        run = self._make_run(
            state={
                "pending_user_message": "fix the tests",
                "pending_user_message_ts": "1234.5",
                "interaction_origin": "slack",
                "sandbox_url": "https://sandbox.example.com/rpc",
            }
        )
        self.SlackThreadTaskMapping = apps.get_model("slack_app", "SlackThreadTaskMapping")
        self.SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.slack_integration,
            slack_workspace_id="T123",
            channel="C123",
            thread_ts="1111.1",
            task=self.task,
            task_run=run,
            mentioning_slack_user_id="U123",
        )

        mock_send.return_value = _command_result(
            success=False,
            status_code=401,
            error="Unauthorized",
            retryable=False,
        )

        forward_pending_user_message(str(run.id))

        mock_enqueue_relay.assert_called_once()
        assert mock_enqueue_relay.call_args.kwargs["run_id"] == str(run.id)
        assert "couldn't deliver your follow-up" in mock_enqueue_relay.call_args.kwargs["text"]
        run.refresh_from_db()
        assert "pending_user_message" not in run.state

    @patch("products.tasks.backend.temporal.client.execute_posthog_code_agent_relay_workflow")
    @patch("products.tasks.backend.services.connection_token.create_sandbox_connection_token", return_value="jwt")
    @patch("products.tasks.backend.services.agent_command.send_user_message")
    def test_slack_origin_posts_fallback_when_reply_text_missing(self, mock_send, mock_token, mock_enqueue_relay):
        run = self._make_run(
            state={
                "pending_user_message": "fix the tests",
                "pending_user_message_ts": "1234.5",
                "interaction_origin": "slack",
                "sandbox_url": "https://sandbox.example.com/rpc",
            }
        )

        mock_send.return_value = _command_result(
            success=True,
            status_code=200,
            data={"result": {}},
        )

        forward_pending_user_message(str(run.id))

        mock_enqueue_relay.assert_called_once()
        assert "couldn't fetch the reply text" in mock_enqueue_relay.call_args.kwargs["text"]
