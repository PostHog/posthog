import json
import time
from typing import Any

from unittest.mock import MagicMock, patch

from django.apps import apps
from django.core.cache import cache
from django.test import TestCase, override_settings

from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.api import (
    UNTAGGED_FOLLOWUP_ACTION_DISMISS,
    UNTAGGED_FOLLOWUP_ACTION_RUN,
    UNTAGGED_FOLLOWUP_BLOCK_ID_PREFIX,
    UNTAGGED_FOLLOWUP_CONTEXT_KIND,
    _picker_context_cache_key,
)
from products.slack_app.backend.models import SlackSettings, SlackThreadTaskMapping, UntaggedFollowupMode
from products.slack_app.backend.tests.helpers import sign_slack_request


@override_settings(DEBUG=True)
@patch("products.slack_app.backend.api.requests.post")
@patch("products.slack_app.backend.api.SlackIntegration")
class TestUntaggedFollowupInteractivity(TestCase):
    """The `ask` mode is only useful if the confirmation actually dispatches the
    message it was raised for. DEBUG=True keeps the endpoint local-only, so an
    unrecognised payload doesn't attempt a real cross-region proxy."""

    signing_secret = "posthog-code-test-secret"
    slack_team_id = "T12345"
    slack_channel_id = "C001"
    response_url = "https://hooks.slack.example/response/abc"
    context_token = "untagged-token-123"

    def setUp(self):
        cache.clear()
        self.client = APIClient()

        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.member_user = User.objects.create(email="member@example.com", distinct_id="user-member")
        OrganizationMembership.objects.create(user=self.member_user, organization=self.organization)
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id=self.slack_team_id,
            sensitive_config={"access_token": "xoxb-test"},
        )

        # The prompt only exists because the thread is mapped to a task, and the
        # click re-reads that mapping to see the creator's current mode.
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(
            team=self.team,
            title="Fix the broken dashboard export",
            description="desc",
            origin_product=Task.OriginProduct.SLACK,
            created_by=self.member_user,
            repository="org/repo",
        )
        self.mapping = SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id=self.slack_team_id,
            channel=self.slack_channel_id,
            thread_ts="1000.0000",
            task=task,
            task_run=TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS),
            mentioning_slack_user_id="U_ALICE",
        )
        SlackSettings.objects.create(
            slack_workspace_id=self.slack_team_id,
            slack_user_id="U_ALICE",
            untagged_followup_mode=UntaggedFollowupMode.ASK,
        )

        self.event = {
            "type": "message",
            "channel": self.slack_channel_id,
            "user": "U_BOB",
            "ts": "1001.0000",
            "thread_ts": "1000.0000",
            "text": "and the export filter too",
        }
        cache.set(
            _picker_context_cache_key(self.context_token),
            {
                "kind": UNTAGGED_FOLLOWUP_CONTEXT_KIND,
                "integration_id": self.integration.id,
                "slack_workspace_id": self.slack_team_id,
                "slack_channel_id": self.slack_channel_id,
                "thread_ts": "1000.0000",
                "slack_user_id": "U_BOB",
                "event": self.event,
                "is_ext_shared_channel": False,
                "created_at": int(time.time()),
            },
            timeout=900,
        )

        self._ff_patcher = patch(
            "products.slack_app.backend.api.is_slack_app_untagged_thread_followups_enabled", return_value=True
        )
        self._ff_patcher.start()
        self.addCleanup(self._ff_patcher.stop)

    def _click(self, action_id: str, slack_user_id: str) -> Any:
        payload = {
            "type": "block_actions",
            "team": {"id": self.slack_team_id},
            "user": {"id": slack_user_id},
            "response_url": self.response_url,
            "actions": [
                {
                    "action_id": action_id,
                    "block_id": f"{UNTAGGED_FOLLOWUP_BLOCK_ID_PREFIX}_actions:{self.context_token}",
                    "value": self.context_token,
                }
            ],
        }
        body_str = f"payload={json.dumps(payload)}"
        signed = sign_slack_request(body_str.encode(), self.signing_secret)
        return self.client.post(
            "/slack/interactivity-callback/",
            data=body_str,
            content_type="application/x-www-form-urlencoded",
            headers={"x-slack-signature": signed.signature, "x-slack-request-timestamp": signed.timestamp},
        )

    def _stub_slack_user_email(self, email: str) -> Any:
        return patch(
            "products.slack_app.backend.api.get_slack_user_info",
            return_value={"user": {"profile": {"email": email}}},
        )

    def test_confirmation_dispatches_the_original_message(self, mock_slack_cls, mock_post):
        mock_slack_cls.slack_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}

        with (
            self._stub_slack_user_email(self.member_user.email),
            patch("products.slack_app.backend.api._start_mention_workflow") as mock_start,
        ):
            response = self._click(UNTAGGED_FOLLOWUP_ACTION_RUN, "U_BOB")

        assert response.status_code == 200
        mock_start.assert_called_once()
        assert mock_start.call_args.args[0] == self.event
        assert mock_start.call_args.kwargs["untagged_followup"] is True
        # Without this the re-dispatch would classify again and re-raise the prompt.
        assert mock_start.call_args.kwargs["untagged_followup_confirmed"] is True
        assert mock_start.call_args.kwargs["posthog_user"].id == self.member_user.id
        # Burnt on use, so a forwarded or double click can't run the same message twice.
        assert cache.get(_picker_context_cache_key(self.context_token)) is None
        assert mock_post.call_args.kwargs["json"] == {"delete_original": True}

    def test_dismissal_dispatches_nothing(self, mock_slack_cls, mock_post):
        mock_slack_cls.slack_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}

        with patch("products.slack_app.backend.api._start_mention_workflow") as mock_start:
            response = self._click(UNTAGGED_FOLLOWUP_ACTION_DISMISS, "U_BOB")

        assert response.status_code == 200
        mock_start.assert_not_called()
        assert cache.get(_picker_context_cache_key(self.context_token)) is None
        assert mock_post.call_args.kwargs["json"] == {"delete_original": True}

    def test_click_from_anyone_but_the_message_author_dispatches_nothing(self, mock_slack_cls, mock_post):
        # The prompt is ephemeral, so this shouldn't be reachable — but the run
        # would execute as the clicker against somebody else's message.
        mock_slack_cls.slack_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}

        with (
            self._stub_slack_user_email(self.member_user.email),
            patch("products.slack_app.backend.api._start_mention_workflow") as mock_start,
        ):
            response = self._click(UNTAGGED_FOLLOWUP_ACTION_RUN, "U_SOMEONE_ELSE")

        assert response.status_code == 200
        mock_start.assert_not_called()

    def test_flag_turned_off_between_prompt_and_click_dispatches_nothing(self, mock_slack_cls, mock_post):
        mock_slack_cls.slack_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        self._ff_patcher.stop()

        with (
            patch("products.slack_app.backend.api.is_slack_app_untagged_thread_followups_enabled", return_value=False),
            self._stub_slack_user_email(self.member_user.email),
            patch("products.slack_app.backend.api._start_mention_workflow") as mock_start,
        ):
            response = self._click(UNTAGGED_FOLLOWUP_ACTION_RUN, "U_BOB")

        self._ff_patcher.start()
        assert response.status_code == 200
        mock_start.assert_not_called()

    def test_confirmation_after_the_creator_switched_to_never_dispatches_nothing(self, mock_slack_cls, mock_post):
        # The confirmed run skips the mode activity, so the click is the last place
        # that can honour a mode changed while the prompt sat unanswered.
        mock_slack_cls.slack_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        SlackSettings.objects.filter(slack_user_id="U_ALICE").update(untagged_followup_mode=UntaggedFollowupMode.NEVER)

        with (
            self._stub_slack_user_email(self.member_user.email),
            patch("products.slack_app.backend.api._start_mention_workflow") as mock_start,
        ):
            response = self._click(UNTAGGED_FOLLOWUP_ACTION_RUN, "U_BOB")

        assert response.status_code == 200
        mock_start.assert_not_called()

    def test_confirmation_from_a_member_without_project_access_dispatches_nothing(self, mock_slack_cls, mock_post):
        # Org membership is all `_is_org_member` proves. The routing path drops a reply
        # whose author can't reach the mapped project, so the click has to as well.
        mock_slack_cls.slack_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}

        no_access = MagicMock()
        no_access.team.return_value.effective_membership_level = None
        with (
            self._stub_slack_user_email(self.member_user.email),
            patch("products.slack_app.backend.api.UserPermissions", return_value=no_access),
            patch("products.slack_app.backend.api._start_mention_workflow") as mock_start,
        ):
            response = self._click(UNTAGGED_FOLLOWUP_ACTION_RUN, "U_BOB")

        assert response.status_code == 200
        mock_start.assert_not_called()

    def test_thread_whose_mapping_disappeared_dispatches_nothing(self, mock_slack_cls, mock_post):
        mock_slack_cls.slack_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        self.mapping.delete()

        with (
            self._stub_slack_user_email(self.member_user.email),
            patch("products.slack_app.backend.api._start_mention_workflow") as mock_start,
        ):
            response = self._click(UNTAGGED_FOLLOWUP_ACTION_RUN, "U_BOB")

        assert response.status_code == 200
        mock_start.assert_not_called()
