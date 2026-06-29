from types import SimpleNamespace

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.api import _decode_picker_context
from products.slack_app.backend.models import SlackAutonomyTier, SlackThreadTaskMapping
from products.slack_app.backend.services.agent_permissions import (
    SLACK_PERMISSION_ACTION_APPROVE,
    SLACK_PERMISSION_ACTION_DENY,
    SLACK_PERMISSION_ACTION_SELECT,
    SLACK_PERMISSION_CONTEXT_KIND,
    _permission_prompt_dedupe_key,
    handle_slack_permission_request_for_task_run,
    post_slack_permission_request_for_task_run,
)
from products.tasks.backend.models import Task, TaskRun


class TestSlackAgentPermissionPrompt(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-1")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-test"},
        )
        self.task = Task.objects.create(
            team=self.team,
            title="Create a PDF",
            created_by=self.user,
            origin_product=Task.OriginProduct.SLACK,
        )
        self.task_run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"sandbox_url": "https://sandbox.example.com"},
        )
        self.mapping = SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T12345",
            channel="C123",
            thread_ts="1700000000.000001",
            task=self.task,
            task_run=self.task_run,
            mentioning_slack_user_id="U_ORIGINAL",
            latest_actor_slack_user_id="U_ACTOR",
        )

    def _permission_event(self) -> dict:
        return {
            "type": "permission_request",
            "requestId": "perm-1",
            "options": [
                {"kind": "allow_once", "name": "Yes", "optionId": "allow"},
                {"kind": "allow_always", "name": "Yes, and don't ask again for this command", "optionId": "always"},
                {"kind": "reject_once", "name": "No", "optionId": "reject"},
            ],
            "toolCall": {
                "title": "Check available PDF generation tools",
                "rawInput": {
                    "toolName": "Bash",
                    "description": "Check available PDF generation tools",
                    "command": 'python3 -c "import reportlab"',
                },
            },
        }

    def _permission_notification_event(self) -> dict:
        event = self._permission_event()
        return {
            "type": "notification",
            "notification": {
                "method": "_posthog/permission_request",
                "params": {key: value for key, value in event.items() if key != "type"},
            },
        }

    def _posthog_exec_permission_event(self, tool_name: str, request_id: str = "perm-1") -> dict:
        event = self._permission_event()
        event["requestId"] = request_id
        event["toolCall"] = {
            "title": f"Call {tool_name}",
            "rawInput": {
                "toolName": "mcp__posthog__exec",
                "description": f"Call {tool_name}",
                "command": f'call --json {tool_name} {{"id": "artifact-1"}}',
            },
        }
        return event

    @patch("products.slack_app.backend.services.agent_permissions.SlackIntegration")
    def test_posts_threaded_permission_prompt(self, mock_slack_cls: MagicMock) -> None:
        post_slack_permission_request_for_task_run(self.task_run, self._permission_event())

        mock_chat = mock_slack_cls.return_value.client.chat_postMessage
        mock_chat.assert_called_once()
        call_kwargs = mock_chat.call_args.kwargs
        assert call_kwargs["channel"] == "C123"
        assert call_kwargs["thread_ts"] == "1700000000.000001"
        assert "<@U_ACTOR>" in call_kwargs["text"]

        blocks = call_kwargs["blocks"]
        assert blocks[0]["type"] == "section"
        assert "Agent approval needed" in blocks[0]["text"]["text"]
        assert "<@U_ACTOR>" in blocks[0]["text"]["text"]
        assert blocks[1]["type"] == "section"
        assert "Check available PDF generation tools" in blocks[1]["text"]["text"]
        assert '```python3 -c "import reportlab"```' in blocks[1]["text"]["text"]

        assert blocks[2]["type"] == "actions"
        permission_actions = blocks[2]["elements"]
        approve_button = next(
            element for element in permission_actions if element["action_id"] == SLACK_PERMISSION_ACTION_APPROVE
        )
        deny_button = next(
            element for element in permission_actions if element["action_id"] == SLACK_PERMISSION_ACTION_DENY
        )
        assert approve_button["style"] == "primary"
        assert "style" not in deny_button

        assert blocks[3]["type"] == "actions"
        config_select = blocks[3]["elements"][0]
        assert config_select["action_id"] == SLACK_PERMISSION_ACTION_SELECT
        assert config_select["initial_option"]["value"] == SlackAutonomyTier.ASK_BEFORE_WRITE
        assert [option["value"] for option in config_select["options"]] == [
            SlackAutonomyTier.READ_ONLY,
            SlackAutonomyTier.ASK_BEFORE_WRITE,
            SlackAutonomyTier.FULL_AUTO,
        ]

        context_token = call_kwargs["metadata"]["event_payload"]["context_token"]
        context = _decode_picker_context(context_token)
        assert context is not None
        assert context["kind"] == SLACK_PERMISSION_CONTEXT_KIND
        assert context["run_id"] == str(self.task_run.id)
        assert context["request_id"] == "perm-1"
        assert context["expected_slack_user_id"] == "U_ACTOR"
        assert context["reject_option_id"] == "reject"
        assert context["tool_label"] == "Check available PDF generation tools"
        assert context["tool_detail"] == 'python3 -c "import reportlab"'

    @patch("products.slack_app.backend.services.agent_permissions.SlackIntegration")
    def test_dedupes_repeated_permission_request(self, mock_slack_cls: MagicMock) -> None:
        event = self._permission_event()

        post_slack_permission_request_for_task_run(self.task_run, event)
        post_slack_permission_request_for_task_run(self.task_run, event)

        mock_slack_cls.return_value.client.chat_postMessage.assert_called_once()

    @patch("products.slack_app.backend.services.agent_permissions.SlackIntegration")
    def test_failed_post_does_not_dedupe_permission_request(self, mock_slack_cls: MagicMock) -> None:
        mock_slack_cls.return_value.client.chat_postMessage.side_effect = SlackApiError(
            "invalid blocks",
            response={"ok": False, "error": "invalid_blocks"},
        )

        post_slack_permission_request_for_task_run(self.task_run, self._permission_event())

        assert cache.get(_permission_prompt_dedupe_key(str(self.task_run.id), "perm-1")) is None

    @patch("products.slack_app.backend.services.agent_permissions.SlackIntegration")
    def test_posts_prompt_from_agent_notification_shape(self, mock_slack_cls: MagicMock) -> None:
        post_slack_permission_request_for_task_run(self.task_run, self._permission_notification_event())

        mock_chat = mock_slack_cls.return_value.client.chat_postMessage
        mock_chat.assert_called_once()
        call_kwargs = mock_chat.call_args.kwargs
        assert call_kwargs["channel"] == "C123"
        assert call_kwargs["thread_ts"] == "1700000000.000001"
        assert call_kwargs["metadata"]["event_payload"]["request_id"] == "perm-1"

    @patch("products.slack_app.backend.services.agent_permissions.SlackIntegration")
    def test_permission_body_respects_slack_limit(self, mock_slack_cls: MagicMock) -> None:
        event = self._permission_event()
        event["toolCall"]["rawInput"]["command"] = "python3 -c " + ("'print(1)'; " * 400)

        post_slack_permission_request_for_task_run(self.task_run, event)

        blocks = mock_slack_cls.return_value.client.chat_postMessage.call_args.kwargs["blocks"]
        body = blocks[1]
        assert body["type"] == "section"
        assert len(body["text"]["text"]) <= 2900

    @patch("products.tasks.backend.temporal.client.signal_task_permission_response")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.services.agent_permissions.SlackIntegration")
    def test_full_auto_posthog_tool_is_broker_approved_without_prompt(
        self,
        mock_slack_cls: MagicMock,
        mock_resolve_slack_user: MagicMock,
        mock_signal_permission_response: MagicMock,
    ) -> None:
        self.task_run.state = {"slack_autonomy_tier": SlackAutonomyTier.FULL_AUTO}
        self.task_run.save(update_fields=["state"])
        event = self._posthog_exec_permission_event("tasks-runs-living-artifacts-create")
        mock_resolve_slack_user.return_value = SimpleNamespace(user=self.user, slack_email=self.user.email)

        handle_slack_permission_request_for_task_run(self.task_run, event)

        mock_slack_cls.return_value.client.chat_postMessage.assert_not_called()
        mock_signal_permission_response.assert_called_once_with(
            self.task_run.workflow_id,
            request_id="perm-1",
            option_id="allow",
            actor_user_id=self.user.id,
            actor_slack_user_id="U_ACTOR",
            effect_class="internal_write",
            broker_reason="full_auto_internal_write",
        )

    @patch("products.tasks.backend.temporal.client.signal_task_permission_response")
    @patch("products.slack_app.backend.services.agent_permissions.SlackIntegration")
    def test_posts_prompt_for_destructive_posthog_tool(
        self,
        mock_slack_cls: MagicMock,
        mock_signal_permission_response: MagicMock,
    ) -> None:
        event = self._posthog_exec_permission_event("skill-file-delete")

        handle_slack_permission_request_for_task_run(self.task_run, event)

        mock_signal_permission_response.assert_not_called()
        mock_slack_cls.return_value.client.chat_postMessage.assert_called_once()

    @patch("products.tasks.backend.temporal.client.signal_task_permission_response")
    @patch("products.slack_app.backend.services.agent_permissions.SlackIntegration")
    def test_posts_prompt_for_destructive_shell_command(
        self,
        mock_slack_cls: MagicMock,
        mock_signal_permission_response: MagicMock,
    ) -> None:
        event = self._permission_event()
        event["toolCall"]["rawInput"]["command"] = "rm -rf report.xlsx"

        handle_slack_permission_request_for_task_run(self.task_run, event)

        mock_signal_permission_response.assert_not_called()
        mock_slack_cls.return_value.client.chat_postMessage.assert_called_once()

    @patch("products.tasks.backend.temporal.client.signal_task_permission_response")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.services.agent_permissions.SlackIntegration")
    def test_full_auto_internal_write_is_broker_approved(
        self,
        mock_slack_cls: MagicMock,
        mock_resolve_slack_user: MagicMock,
        mock_signal_permission_response: MagicMock,
    ) -> None:
        self.task_run.state = {"slack_autonomy_tier": SlackAutonomyTier.FULL_AUTO}
        self.task_run.save(update_fields=["state"])
        event = self._permission_event()
        event["toolCall"]["rawInput"]["description"] = "Create a living artifact"
        event["toolCall"]["rawInput"]["command"] = (
            "curl -X POST $POSTHOG_API_URL/api/projects/$POSTHOG_PROJECT_ID/tasks/"
            "$POSTHOG_TASK_ID/runs/$POSTHOG_TASK_RUN_ID/living_artifacts/"
        )
        mock_resolve_slack_user.return_value = SimpleNamespace(user=self.user, slack_email=self.user.email)

        post_slack_permission_request_for_task_run(self.task_run, event)

        mock_slack_cls.return_value.client.chat_postMessage.assert_not_called()
        mock_signal_permission_response.assert_called_once_with(
            self.task_run.workflow_id,
            request_id="perm-1",
            option_id="allow",
            actor_user_id=self.user.id,
            actor_slack_user_id="U_ACTOR",
            effect_class="internal_write",
            broker_reason="full_auto_internal_write",
        )

    @patch("products.tasks.backend.temporal.client.signal_task_permission_response")
    @patch("products.slack_app.backend.services.agent_permissions.SlackIntegration")
    def test_full_auto_customer_facing_request_still_posts_prompt(
        self,
        mock_slack_cls: MagicMock,
        mock_signal_permission_response: MagicMock,
    ) -> None:
        self.task_run.state = {
            "slack_autonomy_tier": SlackAutonomyTier.FULL_AUTO,
            "slack_is_ext_shared_channel": True,
        }
        self.task_run.save(update_fields=["state"])
        event = self._permission_event()
        event["toolCall"]["rawInput"]["description"] = "Send a Slack file to the customer thread"
        event["toolCall"]["rawInput"]["command"] = "curl -X POST ... living_artifacts adapter=slack_file"

        post_slack_permission_request_for_task_run(self.task_run, event)

        mock_signal_permission_response.assert_not_called()
        mock_slack_cls.return_value.client.chat_postMessage.assert_called_once()
        context_token = mock_slack_cls.return_value.client.chat_postMessage.call_args.kwargs["metadata"][
            "event_payload"
        ]["context_token"]
        context = _decode_picker_context(context_token)
        assert context is not None
        assert context["effect_class"] == "customer_facing"

    @patch("products.tasks.backend.temporal.client.signal_task_permission_response")
    @patch("products.slack_app.backend.services.agent_permissions.SlackIntegration")
    def test_full_auto_declared_customer_facing_metadata_posts_prompt(
        self,
        mock_slack_cls: MagicMock,
        mock_signal_permission_response: MagicMock,
    ) -> None:
        self.task_run.state = {"slack_autonomy_tier": SlackAutonomyTier.FULL_AUTO}
        self.task_run.save(update_fields=["state"])
        event = self._permission_event()
        event["toolCall"]["rawInput"]["description"] = "Create release notes"
        event["toolCall"]["rawInput"]["command"] = "python3 scripts/render_release_notes.py"
        event["toolCall"]["rawInput"]["metadata"] = {"effect_class": "customer_facing"}

        post_slack_permission_request_for_task_run(self.task_run, event)

        mock_signal_permission_response.assert_not_called()
        mock_slack_cls.return_value.client.chat_postMessage.assert_called_once()
        context_token = mock_slack_cls.return_value.client.chat_postMessage.call_args.kwargs["metadata"][
            "event_payload"
        ]["context_token"]
        context = _decode_picker_context(context_token)
        assert context is not None
        assert context["effect_class"] == "customer_facing"

    @patch("products.tasks.backend.temporal.client.signal_task_permission_response")
    @patch("products.slack_app.backend.services.agent_permissions.SlackIntegration")
    def test_full_auto_external_channel_write_defaults_to_customer_facing(
        self,
        mock_slack_cls: MagicMock,
        mock_signal_permission_response: MagicMock,
    ) -> None:
        self.task_run.state = {
            "slack_autonomy_tier": SlackAutonomyTier.FULL_AUTO,
            "slack_is_ext_shared_channel": True,
        }
        self.task_run.save(update_fields=["state"])
        event = self._permission_event()
        event["toolCall"]["rawInput"]["description"] = "Edit changelog"
        event["toolCall"]["rawInput"]["command"] = "python3 scripts/render_changelog.py"

        post_slack_permission_request_for_task_run(self.task_run, event)

        mock_signal_permission_response.assert_not_called()
        mock_slack_cls.return_value.client.chat_postMessage.assert_called_once()
        context_token = mock_slack_cls.return_value.client.chat_postMessage.call_args.kwargs["metadata"][
            "event_payload"
        ]["context_token"]
        context = _decode_picker_context(context_token)
        assert context is not None
        assert context["effect_class"] == "customer_facing"
