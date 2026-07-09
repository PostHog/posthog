from types import SimpleNamespace

from unittest import TestCase as UnitTestCase
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.test import TestCase

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.temporal.ai.slack_app import (
    PostHogCodeSlackMentionWorkflowInputs,
    create_posthog_code_task_for_repo_activity,
    enforce_posthog_code_billing_quota_activity,
    forward_posthog_code_followup_activity,
)
from posthog.temporal.ai.slack_app.activities.task_creation import _build_terminal_recovery_prompt
from posthog.temporal.ai.slack_app.helpers import safe_react

from products.slack_app.backend.api import SlackUserContext
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


def _assert_quota_denial_posted(mock_slack_instance: MagicMock, channel: str, thread_ts: str) -> None:
    denial_calls = [
        call
        for call in mock_slack_instance.client.chat_postMessage.call_args_list
        if call.kwargs.get("channel") == channel and call.kwargs.get("thread_ts") == thread_ts
    ]
    assert denial_calls, "Expected an in-thread denial message when over quota"
    assert "PostHog AI credits" in denial_calls[0].kwargs["text"]


class TestTerminalRecoveryPrompt(UnitTestCase):
    def test_failed_connector_recovery_prompts_replan(self):
        previous_run = SimpleNamespace(
            id="run-1",
            status="failed",
            error_message="No connected GitHub integration was found for this user",
            state={
                "slack_recovery_strategy": "connect_then_replan",
                "slack_recovery_prompt": "Reply after connecting the missing tool.",
            },
        )

        prompt = _build_terminal_recovery_prompt(previous_run, "I connected GitHub, try again")

        assert "Recovery mode: connect_then_replan" in prompt
        assert "Refresh the current connector/auth state" in prompt
        assert "No connected GitHub integration" in prompt
        assert "I connected GitHub, try again" in prompt


class TestSlackThreadTaskMapping(TestCase):
    def setUp(self):
        self.Task = apps.get_model("tasks", "Task")
        self.TaskRun = apps.get_model("tasks", "TaskRun")
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T_SLACK", config={})
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


class TestCreatePostHogCodeTaskForRepoActivity(TestCase):
    def setUp(self):
        self.Task = apps.get_model("tasks", "Task")
        self.TaskRun = apps.get_model("tasks", "TaskRun")
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com", distinct_id="user-1")
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T_SLACK", config={})
        # The mock SlackIntegration doesn't stub `auth_test`, so `get_cached_bot_user_id`
        # would return None and the bot-mention fast-path strip wouldn't kick in. Force
        # it to return the literal "BOT" so `<@BOT>` in test inputs is stripped from
        # the agent prompt as it would be in production.
        bot_id_patcher = patch(
            "products.slack_app.backend.services.slack_messages.get_cached_bot_user_id",
            return_value="BOT",
        )
        bot_id_patcher.start()
        self.addCleanup(bot_id_patcher.stop)

    @patch("products.tasks.backend.facade.temporal.execute_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_no_repo_task_starts_with_pr_creation_enabled(self, mock_slack_cls, mock_execute_workflow):
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
            self.user.id,
            inputs.event,
            [{"user": "U_ALICE", "text": "run without repo"}],
            None,
        )

        task = self.Task.objects.get(team=self.team)
        assert task.repository is None
        assert task.origin_product == self.Task.OriginProduct.SLACK
        assert task.latest_run.state["interaction_origin"] == "slack"
        assert task.latest_run.state["pr_authorship_mode"] == "bot"

        # Mention-dispatch debug pointer persisted on the new run.
        # No explicit envelope event_id → falls back to "<channel>:<ts>".
        assert task.latest_run.state["slack_mention_workflow_id"] == "posthog-code-mention-T_SLACK:C123:1234.5678"

        mock_execute_workflow.assert_called_once()
        call_kwargs = mock_execute_workflow.call_args.kwargs
        assert call_kwargs["task_id"] == str(task.id)
        assert call_kwargs["run_id"] == str(task.latest_run.id)
        assert call_kwargs["create_pr"] is True
        assert call_kwargs["posthog_mcp_scopes"] == "full"

        mapping = SlackThreadTaskMapping.objects.get(
            integration=self.integration, channel="C123", thread_ts="1234.5678"
        )
        assert mapping.task_id == task.id
        assert mapping.task_run_id == task.latest_run.id

    @patch("products.tasks.backend.facade.temporal.execute_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_persists_explicit_event_id_in_workflow_id(self, mock_slack_cls, mock_execute_workflow):
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance

        inputs = PostHogCodeSlackMentionWorkflowInputs(
            event={"channel": "C123", "ts": "1234.5678", "user": "U_ALICE", "text": "<@BOT> hi"},
            integration_id=self.integration.id,
            slack_team_id="T_SLACK",
            slack_event_id="Ev01234567",
        )
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
            self.user.id,
            inputs.event,
            [{"user": "U_ALICE", "text": "hi"}],
            None,
        )

        task = self.Task.objects.get(team=self.team)
        assert task.latest_run.state["slack_mention_workflow_id"] == "posthog-code-mention-T_SLACK:Ev01234567"

    @patch("products.tasks.backend.facade.temporal.execute_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_persists_repo_research_ids_when_provided(self, mock_slack_cls, mock_execute_workflow):
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
            self.user.id,
            inputs.event,
            [{"user": "U_ALICE", "text": "investigate the flaky checkout test"}],
            None,
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        )

        task = self.Task.objects.get(team=self.team)
        state = task.latest_run.state
        assert state["repo_research_task_id"] == "11111111-1111-1111-1111-111111111111"
        assert state["repo_research_run_id"] == "22222222-2222-2222-2222-222222222222"

    @patch("products.tasks.backend.facade.temporal.execute_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_no_repo_research_ids_when_not_provided(self, mock_slack_cls, mock_execute_workflow):
        # The unambiguous path (explicit mention / cascade auto) never runs the
        # discovery sandbox, so the keys must be absent rather than null.
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
            self.user.id,
            inputs.event,
            [{"user": "U_ALICE", "text": "just answer this, no repo needed"}],
            None,
        )

        task = self.Task.objects.get(team=self.team)
        assert "repo_research_task_id" not in task.latest_run.state
        assert "repo_research_run_id" not in task.latest_run.state

    @patch("products.tasks.backend.facade.temporal.execute_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_no_repo_task_falls_back_to_team_github_integration(self, mock_slack_cls, mock_execute_workflow):
        Integration.objects.create(team=self.team, kind="github", integration_id="12345", config={})
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
            self.user.id,
            inputs.event,
            [{"user": "U_ALICE", "text": "clone a repo later"}],
            None,
        )

        task = self.Task.objects.get(team=self.team)
        assert task.repository is None
        assert task.github_integration is not None
        assert task.github_user_integration is None
        assert task.latest_run.state["pr_authorship_mode"] == "bot"
        mock_execute_workflow.assert_called_once()

    @patch("products.tasks.backend.facade.temporal.execute_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_no_repo_task_falls_back_to_team_github_integration_when_user_token_unusable(
        self, mock_slack_cls, mock_execute_workflow
    ):
        Integration.objects.create(team=self.team, kind="github", integration_id="12345", config={})
        UserIntegration.objects.create(
            user=self.user,
            kind="github",
            integration_id="12345",
            config={"installation_id": "12345"},
            sensitive_config={},
        )
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
            self.user.id,
            inputs.event,
            [{"user": "U_ALICE", "text": "clone a repo later"}],
            None,
        )

        task = self.Task.objects.get(team=self.team)
        assert task.repository is None
        assert task.github_integration is not None
        assert task.github_user_integration is None
        assert task.latest_run.state["pr_authorship_mode"] == "bot"
        mock_execute_workflow.assert_called_once()

    @patch("products.tasks.backend.facade.temporal.execute_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_no_repo_task_prefers_user_github_integration(self, mock_slack_cls, mock_execute_workflow):
        UserIntegration.objects.create(
            user=self.user,
            kind="github",
            integration_id="12345",
            config={"installation_id": "12345"},
            sensitive_config={"user_access_token": "gho_user", "user_refresh_token": "ghr_user"},
        )
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
            self.user.id,
            inputs.event,
            [{"user": "U_ALICE", "text": "clone a repo later"}],
            None,
        )

        task = self.Task.objects.get(team=self.team)
        assert task.repository is None
        assert task.github_user_integration is not None
        assert task.latest_run.state["pr_authorship_mode"] == "user"
        mock_execute_workflow.assert_called_once()

    # Description-format coverage (labeled mentions, indentation, role annotations,
    # forged-tag neutralization, single-message threads, mentioner-from-cache fallback)
    # lives at the helper level in
    # `posthog/temporal/tests/ai/slack_app/activities/test_task_creation.py`. Tests
    # below cover the surrounding activity wiring: Slack permalink, mapping, workflow
    # start, quota blocking, etc.

    @patch("products.tasks.backend.facade.temporal.execute_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_description_is_wired_to_slack_thread_context_helper(self, mock_slack_cls, mock_execute_workflow):
        # Smoke-test that the activity calls into the helper and persists the result —
        # the helper's behaviour is exhaustively tested elsewhere; here we just ensure
        # the wrapper tag survives the round-trip through Task.create_and_run.
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_GEORGIY",
            self.user.id,
            inputs.event,
            [
                {"user": "georgiy", "user_id": "U_GEORGIY", "text": "preamble", "ts": "1.000"},
                {"user": "georgiy", "user_id": "U_GEORGIY", "text": "do something", "ts": "1234.5678"},
            ],
            None,
        )

        task = self.Task.objects.get(team=self.team)
        assert task.description.startswith("<slack_thread_context>")
        assert "</slack_thread_context>" in task.description
        assert task.description.endswith("do something")

    @patch("products.tasks.backend.facade.temporal.execute_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    @patch("ee.billing.quota_limiting.is_team_limited", return_value=True)
    def test_quota_exceeded_blocks_task_creation_with_thread_message(
        self,
        _mock_is_team_limited,
        mock_slack_cls,
        mock_execute_workflow,
    ):
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
            self.user.id,
            inputs.event,
            [{"user": "U_ALICE", "text": "do something"}],
            None,
        )

        # No task created, no workflow started.
        assert not self.Task.objects.filter(team=self.team).exists()
        mock_execute_workflow.assert_not_called()

        _assert_quota_denial_posted(mock_slack_instance, "C123", "1234.5678")


class TestForwardPostHogCodeFollowupActivity(TestCase):
    def setUp(self):
        self.Task = apps.get_model("tasks", "Task")
        self.TaskRun = apps.get_model("tasks", "TaskRun")
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T_SLACK", config={})
        # See note in TestCreatePostHogCodeTaskForRepoActivity.setUp: force the
        # bot-id lookup so `<@BOT>` mentions in test inputs strip the way they
        # do in production.
        bot_id_patcher = patch(
            "products.slack_app.backend.services.slack_messages.get_cached_bot_user_id",
            return_value="BOT",
        )
        bot_id_patcher.start()
        self.addCleanup(bot_id_patcher.stop)
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

    @patch("ee.billing.quota_limiting.is_team_limited", return_value=True)
    @patch("posthog.models.integration.SlackIntegration")
    def test_quota_exceeded_blocks_followup_with_thread_message(
        self,
        mock_slack_cls,
        _mock_is_team_limited,
    ):
        self._create_mapping()
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "do something", "1234.5679"
        )

        # The follow-up was handled by refusal, so the workflow shouldn't fall
        # through to new-task creation.
        assert result is True
        _assert_quota_denial_posted(mock_slack_instance, "C123", "1234.5678")

    @patch("products.tasks.backend.facade.temporal.execute_task_processing_workflow")
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

        # Resume path also annotates the new run with the mention-dispatch pointer.
        assert new_run.state.get("slack_mention_workflow_id") == "posthog-code-mention-T_SLACK:C123:1234.5678"

        mock_slack_instance.client.reactions_add.assert_called_once_with(
            channel="C123", timestamp="1234.5679", name="eyes"
        )
        mock_slack_instance.client.chat_postMessage.assert_not_called()

    @patch("products.tasks.backend.facade.temporal.execute_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_terminal_no_repo_run_resumes_with_pr_creation_enabled(self, mock_slack_cls, mock_execute_workflow):
        self.task.repository = None
        self.task.save()
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.save()
        self._create_mapping()
        mock_slack_cls.return_value = MagicMock()

        inputs = _make_inputs(self.integration.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> clone org/repo and open PR", "1234.5679"
        )

        assert result is True
        mock_execute_workflow.assert_called_once()
        assert mock_execute_workflow.call_args.kwargs["create_pr"] is True

    @patch("products.tasks.backend.facade.temporal.execute_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_terminal_run_seeds_pr_context_into_new_run_prompt(self, mock_slack_cls, mock_execute_workflow):
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
        # Resumed run is told to reuse the PR branch, and carries no per-run notified
        # flag (the "PR opened" card is deduped on the Task).
        assert "gh pr checkout https://github.com/org/repo/pull/1" in new_run.state.get("initial_prompt_override", "")
        assert "gh pr checkout https://github.com/org/repo/pull/1" in new_run.state.get("pending_user_message", "")
        assert "slack_pr_opened_notified" not in new_run.state
        assert "slack_notified_pr_url" not in new_run.state

    @patch("products.tasks.backend.facade.temporal.execute_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_terminal_failed_run_resumes_with_structured_recovery_prompt(self, mock_slack_cls, mock_execute_workflow):
        self.task_run.status = self.TaskRun.Status.FAILED
        self.task_run.error_message = "No connected GitHub integration was found for this user"
        self.task_run.output = {"pr_url": "https://github.com/org/repo/pull/1"}
        self.task_run.state = {
            "slack_recovery_strategy": "connect_then_replan",
            "slack_recovery_prompt": "Reply after connecting the missing tool.",
        }
        self.task_run.save()
        self._create_mapping()
        mock_slack_cls.return_value = MagicMock()

        inputs = _make_inputs(self.integration.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> I connected GitHub, try again", "1234.5679"
        )

        assert result is True
        new_run_id = mock_execute_workflow.call_args.kwargs["run_id"]
        new_run = self.TaskRun.objects.get(id=new_run_id)
        prompt = new_run.state["initial_prompt_override"]
        assert "Recovery mode: connect_then_replan" in prompt
        assert "Refresh the current connector/auth state" in prompt
        assert "No connected GitHub integration" in prompt
        assert "I connected GitHub, try again" in prompt
        assert "gh pr checkout https://github.com/org/repo/pull/1" in prompt
        assert new_run.state["slack_recovery_from_run_id"] == str(self.task_run.id)
        assert new_run.state["slack_recovery_strategy"] == "connect_then_replan"
        assert new_run.state["slack_recovery_user_message"] == "I connected GitHub, try again"

    @patch("products.slack_app.backend.api.resolve_slack_user", return_value=None)
    @patch("posthog.models.integration.SlackIntegration")
    def test_terminal_run_unauthorized_user_returns_true_with_resolver_feedback(self, mock_slack_cls, mock_resolve):
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
        mock_resolve.assert_called_once_with(mock_slack_instance, self.integration, "U_BOB", "C123", "1234.5678")
        mock_slack_instance.client.chat_postMessage.assert_not_called()

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

    @patch("products.tasks.backend.facade.temporal.execute_task_processing_workflow", side_effect=Exception("boom"))
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

    @patch("products.slack_app.backend.api.resolve_slack_user", return_value=None)
    @patch("posthog.models.integration.SlackIntegration")
    def test_unauthorized_actor_returns_true_with_resolver_feedback(self, mock_slack_cls, mock_resolve):
        self._create_mapping(mentioning_user="U_ALICE")
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_BOB", "do something", "1234.5679"
        )
        assert result is True
        mock_resolve.assert_called_once_with(mock_slack_instance, self.integration, "U_BOB", "C123", "1234.5678")
        mock_slack_instance.client.chat_postMessage.assert_not_called()

    @patch(
        "products.tasks.backend.logic.services.connection_token.create_sandbox_connection_token",
        return_value="jwt-token",
    )
    @patch("products.tasks.backend.logic.services.agent_command.send_user_message")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.SlackIntegration")
    def test_cross_user_followup_authorized_prefixes_actor_name(
        self, mock_slack_cls, mock_resolve, mock_send, mock_token
    ):
        # A second user in the same PostHog org and team should be allowed to chip in
        # on the thread; their message is forwarded under their own sandbox identity
        # and their name is prepended so the agent knows who actually spoke.
        self._create_mapping(mentioning_user="U_ALICE")
        bob = User.objects.create(email="bob@test.com", first_name="Bob")
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance
        mock_resolve.return_value = SlackUserContext(user=bob, slack_email="bob@test.com")
        mock_send.return_value = _command_result(success=True, status_code=200)

        inputs = _make_inputs(self.integration.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_BOB", "<@BOT> please retry the build", "1234.5679"
        )

        assert result is True
        assert mock_token.call_args.args[1] == bob.id
        mock_send.assert_called_once_with(
            self.task_run, "Bob: please retry the build", auth_token="jwt-token", timeout=90
        )
        # No "Only the person who started" denial; the message went through.
        post_calls = [
            call
            for call in mock_slack_instance.client.chat_postMessage.call_args_list
            if "Only the person who started" in call.kwargs.get("text", "")
        ]
        assert not post_calls

    @patch(
        "products.tasks.backend.logic.services.connection_token.create_sandbox_connection_token",
        return_value="jwt-token",
    )
    @patch("products.tasks.backend.logic.services.agent_command.send_user_message")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.SlackIntegration")
    def test_cross_user_followup_falls_back_to_email_when_no_full_name(
        self, mock_slack_cls, mock_resolve, mock_send, mock_token
    ):
        self._create_mapping(mentioning_user="U_ALICE")
        bob = User.objects.create(email="bob@test.com")  # no full name
        mock_slack_cls.return_value = MagicMock()
        mock_resolve.return_value = SlackUserContext(user=bob, slack_email="bob@test.com")
        mock_send.return_value = _command_result(success=True, status_code=200)

        inputs = _make_inputs(self.integration.id)
        forward_posthog_code_followup_activity(inputs, "C123", "1234.5678", "U_BOB", "<@BOT> ping", "1234.5679")

        assert mock_token.call_args.args[1] == bob.id
        mock_send.assert_called_once_with(self.task_run, "bob@test.com: ping", auth_token="jwt-token", timeout=90)

    @patch("products.slack_app.backend.api.resolve_slack_user", return_value=None)
    @patch("posthog.models.integration.SlackIntegration")
    def test_cross_user_followup_unmapped_user_delegates_feedback_to_resolver(self, mock_slack_cls, mock_resolve):
        # A second Slack user who can't be resolved to a PostHog member of this team
        # still can't participate, but resolve_slack_user owns the exact feedback
        # because it knows whether email, org membership, or team access failed.
        self._create_mapping(mentioning_user="U_ALICE")
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_BOB", "<@BOT> sneak in", "1234.5679"
        )

        assert result is True
        mock_resolve.assert_called_once_with(mock_slack_instance, self.integration, "U_BOB", "C123", "1234.5678")
        mock_slack_instance.client.chat_postMessage.assert_not_called()

    @patch("products.tasks.backend.facade.temporal.execute_task_processing_workflow")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.SlackIntegration")
    def test_cross_user_terminal_run_resume_prefixes_actor_name(
        self, mock_slack_cls, mock_resolve, mock_execute_workflow
    ):
        # The terminal-resume path goes through `_resume_task_with_new_run`, which has
        # its own user_text derivation. Make sure the prefix lands there too so the
        # new run's initial prompt also carries the actor's name.
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.save()
        self._create_mapping(mentioning_user="U_ALICE")
        bob = User.objects.create(email="bob@test.com", first_name="Bob")
        mock_slack_cls.return_value = MagicMock()
        mock_resolve.return_value = SlackUserContext(user=bob, slack_email="bob@test.com")

        inputs = _make_inputs(self.integration.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_BOB", "<@BOT> fix the tests", "1234.5679"
        )

        assert result is True
        new_run_id = mock_execute_workflow.call_args.kwargs["run_id"]
        new_run = self.TaskRun.objects.get(id=new_run_id)
        assert mock_execute_workflow.call_args.kwargs["user_id"] == bob.id
        assert new_run.state.get("pending_user_message") == "Bob: fix the tests"
        assert new_run.state.get("initial_prompt_override") == "Bob: fix the tests"
        assert new_run.state["slack_actor_user_id"] == bob.id
        assert new_run.state["slack_actor_slack_user_id"] == "U_BOB"

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

    @patch(
        "products.tasks.backend.logic.services.connection_token.create_sandbox_connection_token",
        return_value="jwt-token",
    )
    @patch("products.tasks.backend.logic.services.agent_command.send_user_message")
    @patch("posthog.models.integration.SlackIntegration")
    def test_successful_forwarding(self, mock_slack_cls, mock_send, mock_token):
        mapping = self._create_mapping()
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
        # Agent is now working on the message, so the :eyes: reaction stays up — it is
        # not swapped to :hedgehog: until the task genuinely completes.
        mock_slack_instance.client.reactions_add.assert_called_once_with(
            channel="C123", timestamp="1234.5679", name="eyes"
        )
        mock_slack_instance.client.reactions_remove.assert_not_called()
        # Response is delivered by relayAgentResponse from the agent-server, not by this activity.
        mock_slack_instance.client.chat_postMessage.assert_not_called()
        # The follow-up sender is recorded on the mapping so async reply paths
        # tag the latest actor instead of the original thread creator
        # (multiplayer support). The creator (``mentioning_slack_user_id``)
        # remains immutable; the latest-actor field receives the live actor
        # even when it's the same person as the creator (one-time seed).
        mapping.refresh_from_db()
        assert mapping.latest_actor_slack_user_id == "U_ALICE"
        assert mapping.mentioning_slack_user_id == "U_ALICE"

    @patch(
        "products.tasks.backend.logic.services.connection_token.create_sandbox_connection_token",
        return_value="jwt-token",
    )
    @patch("products.tasks.backend.logic.services.agent_command.send_user_message")
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

    @patch(
        "products.tasks.backend.logic.services.connection_token.create_sandbox_connection_token",
        return_value="jwt-token",
    )
    @patch("products.tasks.backend.logic.services.agent_command.send_user_message")
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
        # The :eyes: reaction stays up while the agent works — no swap to :hedgehog:.
        mock_slack_instance.client.reactions_add.assert_called_once_with(
            channel="C123", timestamp="1234.5679", name="eyes"
        )
        mock_slack_instance.client.reactions_remove.assert_not_called()

    @patch(
        "products.tasks.backend.logic.services.connection_token.create_sandbox_connection_token",
        return_value="jwt-token",
    )
    @patch("products.tasks.backend.logic.services.agent_command.send_user_message")
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
        # The :eyes: reaction stays up while the agent works — no swap to :hedgehog:.
        mock_slack_instance.client.reactions_add.assert_called_once_with(
            channel="C123", timestamp="1234.5679", name="eyes"
        )
        mock_slack_instance.client.reactions_remove.assert_not_called()
        # Response is delivered by relayAgentResponse, not by this activity.
        mock_slack_instance.client.chat_postMessage.assert_not_called()


class TestEnforcePostHogCodeBillingQuotaActivity(TestCase):
    """The workflow's first activity gate. Returns True (and posts a denial) when
    the team is over its AI-credits quota; False otherwise."""

    def setUp(self):
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T_SLACK", config={})

    @patch("posthog.models.integration.SlackIntegration")
    @patch("ee.billing.quota_limiting.is_team_limited", return_value=True)
    def test_returns_true_and_posts_denial_when_over_quota(self, _mock_is_team_limited, mock_slack_cls):
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        blocked = enforce_posthog_code_billing_quota_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
        )

        assert blocked is True
        _assert_quota_denial_posted(mock_slack_instance, "C123", "1234.5678")

    @patch("posthog.models.integration.SlackIntegration")
    @patch("ee.billing.quota_limiting.is_team_limited", return_value=False)
    def test_returns_false_and_posts_nothing_when_under_quota(self, _mock_is_team_limited, mock_slack_cls):
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id)
        blocked = enforce_posthog_code_billing_quota_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
        )

        assert blocked is False
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


class TestSafeReact(UnitTestCase):
    """The 👀/🔍 reaction is cosmetic UX feedback and must never abort an activity."""

    @parameterized.expand(["already_reacted", "message_not_found", "no_reaction", "cant_react"])
    def test_benign_reaction_errors_are_swallowed(self, error_code):
        client = MagicMock()
        client.reactions_add.side_effect = SlackApiError("boom", response={"error": error_code})

        safe_react(client, "C123", "1234.5679", "eyes")

        client.reactions_add.assert_called_once_with(channel="C123", timestamp="1234.5679", name="eyes")

    def test_fatal_reaction_errors_are_reraised(self):
        client = MagicMock()
        client.reactions_add.side_effect = SlackApiError("boom", response={"error": "invalid_auth"})

        with self.assertRaises(SlackApiError):
            safe_react(client, "C123", "1234.5679", "eyes")

    def test_successful_reaction_does_not_raise(self):
        client = MagicMock()

        safe_react(client, "C123", "1234.5679", "eyes")

        client.reactions_add.assert_called_once_with(channel="C123", timestamp="1234.5679", name="eyes")
