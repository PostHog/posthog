from types import SimpleNamespace

from unittest.mock import MagicMock, patch

from django.apps import apps
from django.test import TestCase

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.ai.posthog_code_slack_mention import (
    PostHogCodeSlackMentionWorkflowInputs,
    forward_posthog_code_followup_activity,
)

from products.slack_app.backend.models import SlackThreadTaskMapping


def _make_inputs(integration_id: int, slack_team_id: str = "T_SLACK") -> PostHogCodeSlackMentionWorkflowInputs:
    return PostHogCodeSlackMentionWorkflowInputs(
        event={"channel": "C123", "ts": "1234.5678", "user": "U_ALICE", "text": "<@BOT> do something"},
        integration_id=integration_id,
        slack_team_id=slack_team_id,
    )


def _command_result(**kwargs):
    defaults = {"success": False, "status_code": 0, "error": None, "retryable": False, "data": None}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestSlackThreadTaskMapping(TestCase):
    def setUp(self):
        self.Task = apps.get_model("tasks", "Task")
        self.TaskRun = apps.get_model("tasks", "TaskRun")
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        self.integration = Integration.objects.create(
            team=self.team, kind="slack-posthog-code", integration_id="T_SLACK", config={}
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
        )

    def test_create_mapping(self):
        mapping = SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=self.task,
            task_run=self.task_run,
            mentioning_slack_user_id="U_ALICE",
        )
        assert mapping.pk is not None
        assert mapping.channel == "C123"
        assert mapping.mentioning_slack_user_id == "U_ALICE"

    def test_update_mapping_to_new_run(self):
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=self.task,
            task_run=self.task_run,
            mentioning_slack_user_id="U_ALICE",
        )
        new_run = self.TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=self.TaskRun.Status.QUEUED,
        )
        SlackThreadTaskMapping.objects.update_or_create(
            integration=self.integration,
            channel="C123",
            thread_ts="1234.5678",
            defaults={
                "team": self.team,
                "slack_workspace_id": "T_SLACK",
                "task": self.task,
                "task_run": new_run,
                "mentioning_slack_user_id": "U_ALICE",
            },
        )
        mapping = SlackThreadTaskMapping.objects.get(
            integration=self.integration, channel="C123", thread_ts="1234.5678"
        )
        assert mapping.task_run_id == new_run.id

    def test_unique_constraint(self):
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=self.task,
            task_run=self.task_run,
            mentioning_slack_user_id="U_ALICE",
        )
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            SlackThreadTaskMapping.objects.create(
                team=self.team,
                integration=self.integration,
                slack_workspace_id="T_SLACK",
                channel="C123",
                thread_ts="1234.5678",
                task=self.task,
                task_run=self.task_run,
                mentioning_slack_user_id="U_BOB",
            )


class TestForwardPostHogCodeFollowupActivity(TestCase):
    def setUp(self):
        self.Task = apps.get_model("tasks", "Task")
        self.TaskRun = apps.get_model("tasks", "TaskRun")
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        self.integration = Integration.objects.create(
            team=self.team, kind="slack-posthog-code", integration_id="T_SLACK", config={}
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

    def _create_mapping(self, mentioning_user: str = "U_ALICE") -> SlackThreadTaskMapping:
        return SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=self.task,
            task_run=self.task_run,
            mentioning_slack_user_id=mentioning_user,
        )

    def test_no_mapping_returns_false(self):
        inputs = _make_inputs(self.integration.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "do something", "1234.5679"
        )
        assert result is False

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_terminal_run_resumes_same_task(self, mock_slack_cls, mock_execute_workflow):
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.save()
        self._create_mapping()
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> do something", "1234.5679"
        )

        assert result is True
        mock_execute_workflow.assert_called_once()
        call_kwargs = mock_execute_workflow.call_args.kwargs
        assert call_kwargs["task_id"] == str(self.task.id)
        assert call_kwargs["user_id"] == self.user.id
        assert call_kwargs["create_pr"] is True
        assert call_kwargs["posthog_mcp_scopes"] == "full"

        new_run_id = call_kwargs["run_id"]
        assert new_run_id != str(self.task_run.id)

        mapping = SlackThreadTaskMapping.objects.get(
            integration=self.integration, channel="C123", thread_ts="1234.5678"
        )
        assert str(mapping.task_run_id) == new_run_id
        assert mapping.task_id == self.task.id

        new_run = self.TaskRun.objects.get(id=new_run_id)
        assert new_run.state.get("pending_user_message") == "do something"
        assert new_run.state.get("pending_user_message_ts") == "1234.5679"
        assert new_run.state.get("initial_prompt_override") == "do something"

        mock_slack_instance.client.reactions_add.assert_called_once_with(
            channel="C123", timestamp="1234.5679", name="eyes"
        )
        mock_slack_instance.client.chat_postMessage.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_terminal_run_seeds_pr_url_into_new_run_state(self, mock_slack_cls, mock_execute_workflow):
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.output = {"pr_url": "https://github.com/org/repo/pull/1"}
        self.task_run.save()
        self._create_mapping()
        mock_slack_cls.return_value = MagicMock()

        inputs = _make_inputs(self.integration.id)
        forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> fix the tests", "1234.5679"
        )

        new_run_id = mock_execute_workflow.call_args.kwargs["run_id"]
        new_run = self.TaskRun.objects.get(id=new_run_id)
        assert new_run.state.get("slack_pr_opened_notified") is True
        assert new_run.state.get("slack_notified_pr_url") == "https://github.com/org/repo/pull/1"
        assert "gh pr checkout https://github.com/org/repo/pull/1" in new_run.state.get("initial_prompt_override", "")
        assert "gh pr checkout https://github.com/org/repo/pull/1" in new_run.state.get("pending_user_message", "")

    @patch("posthog.models.integration.SlackIntegration")
    def test_terminal_run_unauthorized_user_returns_true_with_error(self, mock_slack_cls):
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.save()
        self._create_mapping(mentioning_user="U_ALICE")
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_BOB", "<@BOT> do something", "1234.5679"
        )

        assert result is True
        call_kwargs = mock_slack_instance.client.chat_postMessage.call_args.kwargs
        assert "Only the person who started" in call_kwargs["text"]

    @patch("posthog.models.integration.SlackIntegration")
    def test_terminal_run_missing_created_by_returns_true_with_error(self, mock_slack_cls):
        self.task.created_by = None
        self.task.save()
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.save()
        self._create_mapping()
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> do something", "1234.5679"
        )

        assert result is True
        call_kwargs = mock_slack_instance.client.chat_postMessage.call_args.kwargs
        assert "original task creator" in call_kwargs["text"]

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow", side_effect=Exception("boom"))
    @patch("posthog.models.integration.SlackIntegration")
    def test_terminal_run_workflow_start_failure_returns_true_with_error(self, mock_slack_cls, mock_execute_workflow):
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.save()
        self._create_mapping()
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> do something", "1234.5679"
        )

        assert result is True
        call_kwargs = mock_slack_instance.client.chat_postMessage.call_args.kwargs
        assert "internal error" in call_kwargs["text"]

        mapping = SlackThreadTaskMapping.objects.get(
            integration=self.integration, channel="C123", thread_ts="1234.5678"
        )
        assert mapping.task_run_id == self.task_run.id

    @patch("posthog.models.integration.SlackIntegration")
    def test_unauthorized_actor_returns_true_with_message(self, mock_slack_cls):
        self._create_mapping(mentioning_user="U_ALICE")
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_BOB", "do something", "1234.5679"
        )
        assert result is True
        mock_slack_instance.client.chat_postMessage.assert_called_once()
        call_kwargs = mock_slack_instance.client.chat_postMessage.call_args.kwargs
        assert "Only the person who started" in call_kwargs["text"]

    @patch("posthog.models.integration.SlackIntegration")
    def test_sandbox_not_ready_returns_true_with_message(self, mock_slack_cls):
        self.task_run.state = {}
        self.task_run.save()
        self._create_mapping()
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "do something", "1234.5679"
        )
        assert result is True
        call_kwargs = mock_slack_instance.client.chat_postMessage.call_args.kwargs
        assert "still starting up" in call_kwargs["text"]

    @patch("products.tasks.backend.services.connection_token.create_sandbox_connection_token", return_value="jwt-token")
    @patch("products.tasks.backend.services.agent_command.send_user_message")
    @patch("posthog.models.integration.SlackIntegration")
    def test_successful_forwarding(self, mock_slack_cls, mock_send, mock_token):
        self._create_mapping()
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance
        mock_send.return_value = _command_result(
            success=True,
            status_code=200,
            data={"result": {"assistant_message": "thanks"}},
        )

        inputs = _make_inputs(self.integration.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> do something", "1234.5679"
        )

        assert result is True
        mock_token.assert_called_once()
        mock_send.assert_called_once_with(self.task_run, "do something", auth_token="jwt-token", timeout=90)
        assert mock_slack_instance.client.reactions_add.call_count == 2
        mock_slack_instance.client.reactions_remove.assert_any_call(channel="C123", timestamp="1234.5679", name="eyes")
        mock_slack_instance.client.reactions_remove.assert_any_call(
            channel="C123", timestamp="1234.5679", name="seedling"
        )
        # Response is delivered by relayAgentResponse from the agent-server, not by this activity.
        mock_slack_instance.client.chat_postMessage.assert_not_called()

    @patch("products.tasks.backend.services.connection_token.create_sandbox_connection_token", return_value="jwt-token")
    @patch("products.tasks.backend.services.agent_command.send_user_message")
    @patch("posthog.models.integration.SlackIntegration")
    def test_forwarding_failure_posts_error(self, mock_slack_cls, mock_send, mock_token):
        self._create_mapping()
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance
        mock_send.return_value = _command_result(success=False, status_code=401, error="Unauthorized", retryable=False)

        inputs = _make_inputs(self.integration.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> do something", "1234.5679"
        )
        assert result is True
        call_kwargs = mock_slack_instance.client.chat_postMessage.call_args.kwargs
        assert "couldn't deliver" in call_kwargs["text"]

    @patch("products.tasks.backend.services.connection_token.create_sandbox_connection_token", return_value="jwt-token")
    @patch("products.tasks.backend.services.agent_command.send_user_message")
    @patch("posthog.models.integration.SlackIntegration")
    def test_timeout_delegates_to_relay_without_posting(self, mock_slack_cls, mock_send, mock_token):
        self._create_mapping()
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance
        mock_send.return_value = _command_result(
            success=False, status_code=504, error="Sandbox request timed out", retryable=True
        )

        inputs = _make_inputs(self.integration.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> do something", "1234.5679"
        )

        assert result is True
        mock_send.assert_called_once()
        # Agent is still processing — relayAgentResponse delivers the response.
        mock_slack_instance.client.chat_postMessage.assert_not_called()
        mock_slack_instance.client.reactions_remove.assert_any_call(channel="C123", timestamp="1234.5679", name="eyes")
        mock_slack_instance.client.reactions_remove.assert_any_call(
            channel="C123", timestamp="1234.5679", name="seedling"
        )

    @patch("products.tasks.backend.services.connection_token.create_sandbox_connection_token", return_value="jwt-token")
    @patch("products.tasks.backend.services.agent_command.send_user_message")
    @patch("posthog.models.integration.SlackIntegration")
    def test_connection_error_retries_and_succeeds(self, mock_slack_cls, mock_send, mock_token):
        self._create_mapping()
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance
        mock_send.side_effect = [
            _command_result(success=False, status_code=502, error="Connection to sandbox failed", retryable=True),
            _command_result(success=True, status_code=200),
        ]

        inputs = _make_inputs(self.integration.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> do something", "1234.5679"
        )

        assert result is True
        assert mock_send.call_count == 2
        mock_slack_instance.client.reactions_remove.assert_any_call(channel="C123", timestamp="1234.5679", name="eyes")
        mock_slack_instance.client.reactions_remove.assert_any_call(
            channel="C123", timestamp="1234.5679", name="seedling"
        )
        # Response is delivered by relayAgentResponse, not by this activity.
        mock_slack_instance.client.chat_postMessage.assert_not_called()


class TestEventLevelDedupe(TestCase):
    """Verify that the workflow ID format supports event-level deduplication."""

    def test_same_event_id_produces_same_workflow_id(self):
        slack_team_id = "T_SLACK"
        event_id = "Ev123456"
        event_id_or_fallback = event_id
        wf_id_1 = f"posthog-code-mention-{slack_team_id}:{event_id_or_fallback}"
        wf_id_2 = f"posthog-code-mention-{slack_team_id}:{event_id_or_fallback}"
        assert wf_id_1 == wf_id_2

    def test_different_event_ids_produce_different_workflow_ids(self):
        slack_team_id = "T_SLACK"
        wf_id_1 = f"posthog-code-mention-{slack_team_id}:Ev111"
        wf_id_2 = f"posthog-code-mention-{slack_team_id}:Ev222"
        assert wf_id_1 != wf_id_2

    def test_fallback_uses_channel_and_ts(self):
        slack_team_id = "T_SLACK"
        event_id = None
        channel = "C123"
        ts = "1234.5678"
        event_id_or_fallback = event_id if event_id else f"{channel}:{ts}"
        wf_id = f"posthog-code-mention-{slack_team_id}:{event_id_or_fallback}"
        assert wf_id == "posthog-code-mention-T_SLACK:C123:1234.5678"
