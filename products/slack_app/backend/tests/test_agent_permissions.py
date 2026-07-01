from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.api import _decode_picker_context
from products.slack_app.backend.models import SlackPermissionMode, SlackThreadTaskMapping
from products.slack_app.backend.services.agent_permissions import (
    SLACK_PERMISSION_ACTION_APPROVE,
    SLACK_PERMISSION_ACTION_DENY,
    SLACK_PERMISSION_ACTION_SELECT,
    SLACK_PERMISSION_CONTEXT_KIND,
    _permission_prompt_dedupe_key,
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

    def _permission_request(self) -> dict:
        return {
            "request_id": "perm-1",
            "tool_call": {
                "title": "Check available PDF generation tools",
                "rawInput": {
                    "toolName": "Bash",
                    "description": "Check available PDF generation tools",
                    "command": 'python3 -c "import reportlab"',
                },
            },
            "options": [
                {"optionId": "allow", "kind": "allow_once", "name": "Yes"},
                {"optionId": "always", "kind": "allow_always", "name": "Yes, and don't ask again for this command"},
                {"optionId": "reject", "kind": "reject_once", "name": "No"},
            ],
        }

    @patch("products.slack_app.backend.services.agent_permissions.SlackIntegration")
    def test_posts_threaded_permission_prompt(self, mock_slack_cls: MagicMock) -> None:
        post_slack_permission_request_for_task_run(self.task_run, self._permission_request())

        mock_chat = mock_slack_cls.return_value.client.chat_postMessage
        mock_chat.assert_called_once()
        call_kwargs = mock_chat.call_args.kwargs
        assert call_kwargs["channel"] == "C123"
        assert call_kwargs["thread_ts"] == "1700000000.000001"
        assert "<@U_ACTOR>" in call_kwargs["text"]

        blocks = call_kwargs["blocks"]
        assert blocks[0]["type"] == "card"
        assert blocks[0]["slack_icon"]["name"] == "rocket"
        card_actions = blocks[0]["actions"]
        approve_button = next(
            element for element in card_actions if element["action_id"] == SLACK_PERMISSION_ACTION_APPROVE
        )
        deny_button = next(element for element in card_actions if element["action_id"] == SLACK_PERMISSION_ACTION_DENY)
        assert approve_button["style"] == "primary"
        assert "style" not in deny_button

        assert blocks[1]["type"] == "actions"
        config_select = blocks[1]["elements"][0]
        assert config_select["action_id"] == SLACK_PERMISSION_ACTION_SELECT
        assert config_select["initial_option"]["value"] == SlackPermissionMode.ASK_BEFORE_WRITE
        assert [option["value"] for option in config_select["options"]] == [
            SlackPermissionMode.READ_ONLY,
            SlackPermissionMode.ASK_BEFORE_WRITE,
            SlackPermissionMode.FULL_AUTO,
        ]

        context_token = call_kwargs["metadata"]["event_payload"]["context_token"]
        context = _decode_picker_context(context_token)
        assert context is not None
        assert context["kind"] == SLACK_PERMISSION_CONTEXT_KIND
        assert context["run_id"] == str(self.task_run.id)
        assert context["request_id"] == "perm-1"
        assert context["expected_slack_user_id"] == "U_ACTOR"
        assert context["default_option_id"] == "allow"
        assert context["reject_option_id"] == "reject"
        assert context["tool_label"] == "Check available PDF generation tools"
        assert context["tool_detail"] == 'python3 -c "import reportlab"'
        assert [option["label"] for option in context["options"]] == [
            "Allow once",
            "Always allow this command",
            "Deny once",
        ]

    @patch("products.slack_app.backend.services.agent_permissions.SlackIntegration")
    def test_select_reflects_run_permission_mode(self, mock_slack_cls: MagicMock) -> None:
        self.task_run.state = {"slack_permission_mode": SlackPermissionMode.FULL_AUTO}
        self.task_run.save(update_fields=["state"])

        post_slack_permission_request_for_task_run(self.task_run, self._permission_request())

        blocks = mock_slack_cls.return_value.client.chat_postMessage.call_args.kwargs["blocks"]
        config_select = blocks[1]["elements"][0]
        assert config_select["initial_option"]["value"] == SlackPermissionMode.FULL_AUTO

    @patch("products.slack_app.backend.services.agent_permissions.SlackIntegration")
    def test_dedupes_repeated_permission_request(self, mock_slack_cls: MagicMock) -> None:
        request = self._permission_request()

        post_slack_permission_request_for_task_run(self.task_run, request)
        post_slack_permission_request_for_task_run(self.task_run, request)

        mock_slack_cls.return_value.client.chat_postMessage.assert_called_once()

    @patch("products.slack_app.backend.services.agent_permissions.SlackIntegration")
    def test_failed_post_does_not_dedupe_permission_request(self, mock_slack_cls: MagicMock) -> None:
        mock_slack_cls.return_value.client.chat_postMessage.side_effect = SlackApiError(
            "invalid blocks",
            response={"ok": False, "error": "invalid_blocks"},
        )

        post_slack_permission_request_for_task_run(self.task_run, self._permission_request())

        assert cache.get(_permission_prompt_dedupe_key(str(self.task_run.id), "perm-1")) is None

    @patch("products.slack_app.backend.services.agent_permissions.SlackIntegration")
    def test_card_body_respects_slack_limit(self, mock_slack_cls: MagicMock) -> None:
        request = self._permission_request()
        request["tool_call"]["rawInput"]["command"] = "python3 -c " + ("'print(1)'; " * 100)

        post_slack_permission_request_for_task_run(self.task_run, request)

        blocks = mock_slack_cls.return_value.client.chat_postMessage.call_args.kwargs["blocks"]
        card = blocks[0]
        assert card["type"] == "card"
        assert len(card["body"]["text"]) <= 200
