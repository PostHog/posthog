import json
import time
from types import SimpleNamespace
from typing import Any

from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.api import _picker_context_cache_key
from products.slack_app.backend.models import SlackPermissionMode, SlackSettings
from products.slack_app.backend.services.agent_permissions import (
    SLACK_PERMISSION_ACTION_APPROVE,
    SLACK_PERMISSION_ACTION_DENY,
    SLACK_PERMISSION_ACTION_SELECT,
    SLACK_PERMISSION_CONTEXT_KIND,
)
from products.slack_app.backend.tests.helpers import sign_slack_request
from products.tasks.backend.models import Task, TaskRun


class TestPostHogCodeInteractivityHandler(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signing_secret = "posthog-code-test-secret"

    def _post_interactivity(self, payload: dict, **extra_headers) -> Any:
        payload = {"team": {"id": "T12345"}, **payload}
        body_str = f"payload={json.dumps(payload)}"
        body = body_str.encode()
        signature, ts = sign_slack_request(body, self.signing_secret)
        return self.client.post(
            "/slack/interactivity-callback/",
            data=body_str,
            content_type="application/x-www-form-urlencoded",
            HTTP_X_SLACK_SIGNATURE=signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
            **extra_headers,
        )

    def test_get_method_returns_405(self):
        response = self.client.get("/slack/interactivity-callback/")
        assert response.status_code == 405

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_invalid_signature_returns_403(self, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": "different-secret"}
        response = self._post_interactivity({"type": "block_suggestion"})
        assert response.status_code == 403


class TestRepoPickerOptions(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.signing_secret = "posthog-code-test-secret"

        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-1")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)
        self.posthog_code_integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-posthog-code-test"},
        )
        self.github_integration = Integration.objects.create(
            team=self.team,
            kind="github",
            config={"account": {"name": "posthog"}},
            sensitive_config={"access_token": "ghp-test"},
        )

        self.context_token = "test-token-1234"
        self.context_payload = {
            "integration_id": self.posthog_code_integration.id,
            "channel": "C001",
            "thread_ts": "1234.5678",
            "user_message_ts": "1234.5678",
            "mentioning_slack_user_id": "U123",
            "mentioning_user_id": self.user.id,
            "event_text": "fix the bug",
            "created_at": int(time.time()),
        }
        cache.set(f"posthog_code_repo_picker_ctx:{self.context_token}", self.context_payload, timeout=900)

    def _post_interactivity(self, payload: dict) -> Any:
        payload = {"team": {"id": "T12345"}, **payload}
        body_str = f"payload={json.dumps(payload)}"
        body = body_str.encode()
        signature, ts = sign_slack_request(body, self.signing_secret)
        return self.client.post(
            "/slack/interactivity-callback/",
            data=body_str,
            content_type="application/x-www-form-urlencoded",
            headers={"x-slack-signature": signature, "x-slack-request-timestamp": ts},
        )

    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_options_returns_filtered_repos(self, mock_config, mock_get_repos):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_get_repos.return_value = ["posthog/posthog", "posthog/posthog-js", "posthog/hogvm"]

        payload = {
            "type": "block_suggestion",
            "action_id": "posthog_code_repo_select",
            "value": "js",
            "user": {"id": "U123"},
            "block_id": f"posthog_code_repo_picker_v1:{self.context_token}",
        }
        response = self._post_interactivity(payload)
        assert response.status_code == 200
        options = response.json()["options"]
        assert len(options) == 1
        assert options[0]["value"] == "posthog/posthog-js"

    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_options_empty_query_returns_all(self, mock_config, mock_get_repos):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_get_repos.return_value = ["posthog/posthog", "posthog/posthog-js"]

        payload = {
            "type": "block_suggestion",
            "action_id": "posthog_code_repo_select",
            "value": "",
            "user": {"id": "U123"},
            "block_id": f"posthog_code_repo_picker_v1:{self.context_token}",
        }
        response = self._post_interactivity(payload)
        assert response.status_code == 200
        assert len(response.json()["options"]) == 2

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_options_wrong_user_returns_empty(self, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}

        payload = {
            "type": "block_suggestion",
            "action_id": "posthog_code_repo_select",
            "value": "",
            "user": {"id": "U_WRONG"},
            "block_id": f"posthog_code_repo_picker_v1:{self.context_token}",
        }
        response = self._post_interactivity(payload)
        assert response.status_code == 200
        assert response.json()["options"] == []

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_options_expired_token_returns_empty(self, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        cache.delete(f"posthog_code_repo_picker_ctx:{self.context_token}")

        payload = {
            "type": "block_suggestion",
            "action_id": "posthog_code_repo_select",
            "value": "",
            "user": {"id": "U123"},
            "block_id": f"posthog_code_repo_picker_v1:{self.context_token}",
        }
        response = self._post_interactivity(payload)
        assert response.status_code == 200
        assert response.json()["options"] == []

    @patch("posthog.models.integration.WebClient")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_submit_signals_temporal_workflow(
        self, mock_config, mock_sync_connect, mock_asyncio_run, mock_webclient_class
    ):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_webclient_class.return_value = MagicMock()
        self.context_payload["workflow_id"] = "posthog-code-mention-T12345:C001:1234.5678"
        cache.set(f"posthog_code_repo_picker_ctx:{self.context_token}", self.context_payload, timeout=900)

        payload = {
            "type": "block_actions",
            "user": {"id": "U123"},
            "actions": [
                {
                    "action_id": "posthog_code_repo_select",
                    "block_id": f"posthog_code_repo_picker_v1:{self.context_token}",
                    "selected_option": {"value": "posthog/posthog"},
                    "action_ts": "1700000000.123",
                }
            ],
            "message": {"ts": "1234.9999"},
        }
        response = self._post_interactivity(payload)
        assert response.status_code == 200
        mock_sync_connect.assert_called_once()
        mock_sync_connect.return_value.get_workflow_handle.assert_called_once_with(
            "posthog-code-mention-T12345:C001:1234.5678"
        )
        mock_asyncio_run.assert_called_once()
        mock_webclient_class.return_value.chat_update.assert_called_once()

    @patch("posthog.models.integration.WebClient")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_no_repo_button_signals_temporal_workflow(
        self, mock_config, mock_sync_connect, mock_asyncio_run, mock_webclient_class
    ):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_webclient_class.return_value = MagicMock()
        self.context_payload["workflow_id"] = "posthog-code-mention-T12345:C001:1234.5678"
        cache.set(f"posthog_code_repo_picker_ctx:{self.context_token}", self.context_payload, timeout=900)

        payload = {
            "type": "block_actions",
            "user": {"id": "U123"},
            "actions": [
                {
                    "action_id": "posthog_code_repo_none",
                    "block_id": f"posthog_code_repo_picker_v2:{self.posthog_code_integration.id}:U123:{self.context_token}:actions",
                    "value": "no_repo_needed",
                    "action_ts": "1700000000.123",
                }
            ],
            "message": {"ts": "1234.9999"},
        }
        response = self._post_interactivity(payload)
        assert response.status_code == 200
        mock_sync_connect.assert_called_once()
        mock_sync_connect.return_value.get_workflow_handle.assert_called_once_with(
            "posthog-code-mention-T12345:C001:1234.5678"
        )
        mock_asyncio_run.assert_called_once()
        mock_webclient_class.return_value.chat_update.assert_called_once()
        update_call = mock_webclient_class.return_value.chat_update.call_args.kwargs
        assert "without a repository" in update_call["text"].lower()

    @patch("posthog.models.integration.WebClient")
    @patch("products.slack_app.backend.api.sync_connect")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_continue_as_bot_signals_authorship_confirmed(self, mock_config, mock_sync_connect, mock_webclient_class):
        from posthog.temporal.ai.slack_app.posthog_code_slack_mention import PostHogCodeSlackMentionWorkflow

        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_webclient_class.return_value = MagicMock()
        mock_handle = MagicMock()
        mock_handle.signal = AsyncMock()
        mock_sync_connect.return_value.get_workflow_handle.return_value = mock_handle

        payload = {
            "type": "block_actions",
            "user": {"id": "U123"},
            "actions": [
                {
                    "action_id": "posthog_code_continue_as_bot",
                    "value": json.dumps(
                        {
                            "workflow_id": "posthog-code-mention-T12345:C001:1234.5678",
                            "integration_id": self.posthog_code_integration.id,
                            "mentioning_slack_user_id": "U123",
                        }
                    ),
                    "action_ts": "1700000000.123",
                }
            ],
            "channel": {"id": "C001"},
            "message": {"ts": "1234.9999"},
        }
        response = self._post_interactivity(payload)
        assert response.status_code == 200
        mock_sync_connect.return_value.get_workflow_handle.assert_called_once_with(
            "posthog-code-mention-T12345:C001:1234.5678"
        )
        mock_handle.signal.assert_called_once_with(PostHogCodeSlackMentionWorkflow.authorship_confirmed)
        mock_webclient_class.return_value.chat_update.assert_called_once()

    @parameterized.expand(
        [
            ("clicker_mismatch", "U_OTHER", "U123"),
            ("missing_expected_user_fails_closed", "U123", None),
        ]
    )
    @patch("posthog.models.integration.WebClient")
    @patch("products.slack_app.backend.api.sync_connect")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_continue_as_bot_does_not_signal_without_verified_mentioner(
        self, _name, clicker_id, expected_user_id, mock_config, mock_sync_connect, mock_webclient_class
    ):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_webclient_class.return_value = MagicMock()
        mock_handle = MagicMock()
        mock_handle.signal = AsyncMock()
        mock_sync_connect.return_value.get_workflow_handle.return_value = mock_handle

        value = {
            "workflow_id": "posthog-code-mention-T12345:C001:1234.5678",
            "integration_id": self.posthog_code_integration.id,
        }
        if expected_user_id is not None:
            value["mentioning_slack_user_id"] = expected_user_id

        payload = {
            "type": "block_actions",
            "user": {"id": clicker_id},
            "actions": [
                {
                    "action_id": "posthog_code_continue_as_bot",
                    "value": json.dumps(value),
                    "action_ts": "1700000000.123",
                }
            ],
            "channel": {"id": "C001"},
            "message": {"ts": "1234.9999"},
        }
        response = self._post_interactivity(payload)
        assert response.status_code == 200
        mock_sync_connect.assert_not_called()
        mock_handle.signal.assert_not_called()

    @patch("posthog.models.integration.WebClient")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_submit_without_workflow_id_posts_expired(self, mock_config, mock_webclient_class):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        self.context_payload.pop("workflow_id", None)
        cache.set(f"posthog_code_repo_picker_ctx:{self.context_token}", self.context_payload, timeout=900)

        payload = {
            "type": "block_actions",
            "user": {"id": "U123"},
            "actions": [
                {
                    "action_id": "posthog_code_repo_select",
                    "block_id": f"posthog_code_repo_picker_v1:{self.context_token}",
                    "selected_option": {"value": "posthog/posthog"},
                    "action_ts": "1700000000.123",
                }
            ],
            "message": {"ts": "1234.9999"},
        }
        response = self._post_interactivity(payload)
        assert response.status_code == 200
        mock_client.chat_postMessage.assert_called_once()
        assert "selection expired" in mock_client.chat_postMessage.call_args.kwargs["text"].lower()
        assert "posthog again" in mock_client.chat_postMessage.call_args.kwargs["text"].lower()

    def _create_permission_run(self) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="Create PDF",
            created_by=self.user,
            origin_product=Task.OriginProduct.SLACK,
        )
        return TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"sandbox_url": "https://sandbox.example.com"},
        )

    def _cache_permission_context(self, task_run: TaskRun, token: str = "permission-token") -> str:
        cache.set(
            _picker_context_cache_key(token),
            {
                "kind": SLACK_PERMISSION_CONTEXT_KIND,
                "integration_id": self.posthog_code_integration.id,
                "slack_workspace_id": "T12345",
                "channel": "C001",
                "thread_ts": "1234.5678",
                "task_id": str(task_run.task_id),
                "run_id": str(task_run.id),
                "request_id": "perm-1",
                "expected_slack_user_id": "U123",
                "default_option_id": "allow",
                "reject_option_id": "reject",
                "options": [
                    {"optionId": "allow", "kind": "allow_once", "label": "Allow"},
                    {"optionId": "always", "kind": "allow_always", "label": "Always allow this command"},
                    {"optionId": "reject", "kind": "reject_once", "label": "Deny"},
                ],
            },
            timeout=900,
        )
        return token

    def _permission_payload(
        self,
        action_id: str,
        token: str = "permission-token",
        user_id: str = "U123",
    ) -> dict:
        return {
            "type": "block_actions",
            "user": {"id": user_id},
            "response_url": "https://hooks.slack.example/permission",
            "actions": [{"action_id": action_id, "value": token}],
            "channel": {"id": "C001"},
            "message": {"ts": "1234.9999"},
        }

    def _permission_config_payload(
        self,
        token: str = "permission-token",
        user_id: str = "U123",
        selected_mode: str = SlackPermissionMode.FULL_AUTO,
    ) -> dict:
        block_id = f"posthog_code_permission_config:{token}"
        return {
            "type": "block_actions",
            "user": {"id": user_id},
            "response_url": "https://hooks.slack.example/permission",
            "actions": [
                {
                    "action_id": SLACK_PERMISSION_ACTION_SELECT,
                    "block_id": block_id,
                    "selected_option": {"value": selected_mode},
                }
            ],
            "channel": {"id": "C001"},
            "message": {"ts": "1234.9999"},
        }

    @patch("products.slack_app.backend.api.requests.post")
    @patch("products.tasks.backend.facade.api.signal_task_run_permission_response", return_value=True)
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_permission_approve_sends_default_option(
        self,
        mock_config,
        mock_resolve_slack_user,
        mock_signal_permission_response,
        mock_requests_post,
    ):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_resolve_slack_user.return_value = SimpleNamespace(user=self.user, slack_email=self.user.email)
        task_run = self._create_permission_run()
        token = self._cache_permission_context(task_run)

        response = self._post_interactivity(self._permission_payload(SLACK_PERMISSION_ACTION_APPROVE, token))

        assert response.status_code == 200
        mock_signal_permission_response.assert_called_once_with(
            task_run.id,
            task_run.task_id,
            task_run.team_id,
            request_id="perm-1",
            option_id="allow",
            actor_user_id=self.user.id,
            actor_slack_user_id="U123",
            is_denial=False,
            denial_message=None,
            broker_reason="slack_human_response",
        )
        mock_requests_post.assert_called_once()
        assert mock_requests_post.call_args.kwargs["json"]["replace_original"] is True
        assert mock_requests_post.call_args.kwargs["json"]["blocks"][0]["type"] == "card"
        assert "Approved" in mock_requests_post.call_args.kwargs["json"]["text"]
        assert cache.get(_picker_context_cache_key(token)) is None

    @patch("products.slack_app.backend.api.requests.post")
    @patch("products.tasks.backend.facade.api.signal_task_run_permission_response", return_value=True)
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_permission_deny_sends_reject_option(
        self,
        mock_config,
        mock_resolve_slack_user,
        mock_signal_permission_response,
        mock_requests_post,
    ):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_resolve_slack_user.return_value = SimpleNamespace(user=self.user, slack_email=self.user.email)
        task_run = self._create_permission_run()
        token = self._cache_permission_context(task_run)

        response = self._post_interactivity(self._permission_payload(SLACK_PERMISSION_ACTION_DENY, token))

        assert response.status_code == 200
        mock_signal_permission_response.assert_called_once()
        signal_args = mock_signal_permission_response.call_args
        assert signal_args.args == (task_run.id, task_run.task_id, task_run.team_id)
        assert signal_args.kwargs["request_id"] == "perm-1"
        assert signal_args.kwargs["option_id"] == "reject"
        assert signal_args.kwargs["actor_user_id"] == self.user.id
        assert signal_args.kwargs["actor_slack_user_id"] == "U123"
        assert signal_args.kwargs["is_denial"] is True
        assert "denied your approval request" in signal_args.kwargs["denial_message"]
        assert "Try a different safe approach" in signal_args.kwargs["denial_message"]
        assert signal_args.kwargs["broker_reason"] == "slack_human_response"
        assert "Denied" in mock_requests_post.call_args.kwargs["json"]["text"]
        assert "find another path" in mock_requests_post.call_args.kwargs["json"]["text"]

    @patch("products.slack_app.backend.api.requests.post")
    @patch("products.tasks.backend.facade.api.signal_task_run_permission_response")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_permission_deny_keeps_context_when_workflow_signal_fails(
        self,
        mock_config,
        mock_resolve_slack_user,
        mock_signal_permission_response,
        mock_requests_post,
    ):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_resolve_slack_user.return_value = SimpleNamespace(user=self.user, slack_email=self.user.email)
        mock_signal_permission_response.return_value = False
        task_run = self._create_permission_run()
        token = self._cache_permission_context(task_run)

        response = self._post_interactivity(self._permission_payload(SLACK_PERMISSION_ACTION_DENY, token))

        assert response.status_code == 200
        assert mock_requests_post.call_args.kwargs["json"]["response_type"] == "ephemeral"
        assert "couldn't queue that response" in mock_requests_post.call_args.kwargs["json"]["text"]
        assert cache.get(_picker_context_cache_key(token)) is not None

    @patch("products.slack_app.backend.api.requests.post")
    @patch("products.tasks.backend.facade.api.signal_task_run_permission_response")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_permission_wrong_user_gets_ephemeral_feedback(
        self,
        mock_config,
        mock_signal_permission_response,
        mock_requests_post,
    ):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        task_run = self._create_permission_run()
        token = self._cache_permission_context(task_run)

        response = self._post_interactivity(
            self._permission_payload(SLACK_PERMISSION_ACTION_APPROVE, token, user_id="U_OTHER")
        )

        assert response.status_code == 200
        mock_signal_permission_response.assert_not_called()
        mock_requests_post.assert_called_once()
        assert mock_requests_post.call_args.kwargs["json"]["response_type"] == "ephemeral"

    @patch("products.tasks.backend.facade.api.signal_task_run_permission_response")
    @patch("products.slack_app.backend.api.requests.post")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_permission_config_select_persists_user_setting(
        self,
        mock_config,
        mock_requests_post,
        mock_signal_permission_response,
    ):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        # Pre-existing routing pick to a different project — saving a permission mode from an
        # approval card bound to posthog_code_integration must not repoint it.
        routing_team = Team.objects.create(organization=self.organization, name="Other Project")
        routing_integration = Integration.objects.create(
            team=routing_team,
            kind="slack",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-other"},
        )
        SlackSettings.objects.create(
            slack_workspace_id="T12345",
            slack_user_id="U123",
            default_integration=routing_integration,
        )
        task_run = self._create_permission_run()
        token = self._cache_permission_context(task_run)

        response = self._post_interactivity(
            self._permission_config_payload(token, selected_mode=SlackPermissionMode.FULL_AUTO)
        )

        assert response.status_code == 200
        mock_signal_permission_response.assert_not_called()
        settings = SlackSettings.objects.get(slack_workspace_id="T12345", slack_user_id="U123")
        assert settings.default_integration_id == routing_integration.id
        # Scoped to the card's integration only — never a workspace-wide grant.
        assert settings.permission_modes == {str(self.posthog_code_integration.id): SlackPermissionMode.FULL_AUTO}
        task_run.refresh_from_db()
        assert task_run.state["slack_permission_mode"] == SlackPermissionMode.FULL_AUTO
        mock_requests_post.assert_called_once()
        assert mock_requests_post.call_args.kwargs["json"]["response_type"] == "ephemeral"
        assert "Full auto" in mock_requests_post.call_args.kwargs["json"]["text"]
        assert cache.get(_picker_context_cache_key(token)) is not None

    @patch("products.slack_app.backend.api.requests.post")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_permission_click_after_context_expiry_gets_ephemeral_feedback(self, mock_config, mock_requests_post):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}

        response = self._post_interactivity(self._permission_payload(SLACK_PERMISSION_ACTION_APPROVE, "expired-token"))

        assert response.status_code == 200
        mock_requests_post.assert_called_once()
        assert mock_requests_post.call_args.kwargs["json"]["response_type"] == "ephemeral"
        assert "expired" in mock_requests_post.call_args.kwargs["json"]["text"].lower()

    @patch("posthog.models.integration.WebClient")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_submit_signal_failure_posts_expired(
        self,
        mock_config,
        mock_sync_connect,
        mock_asyncio_run,
        mock_webclient_class,
    ):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        self.context_payload["workflow_id"] = "posthog-code-mention-T12345:C001:1234.5678"
        cache.set(f"posthog_code_repo_picker_ctx:{self.context_token}", self.context_payload, timeout=900)
        mock_asyncio_run.side_effect = RuntimeError("workflow not found")

        payload = {
            "type": "block_actions",
            "user": {"id": "U123"},
            "actions": [
                {
                    "action_id": "posthog_code_repo_select",
                    "block_id": f"posthog_code_repo_picker_v1:{self.context_token}",
                    "selected_option": {"value": "posthog/posthog"},
                    "action_ts": "1700000000.123",
                }
            ],
            "message": {"ts": "1234.9999"},
        }
        response = self._post_interactivity(payload)
        assert response.status_code == 200
        mock_sync_connect.assert_called_once()
        mock_client.chat_postMessage.assert_called_once()
        assert "selection expired" in mock_client.chat_postMessage.call_args.kwargs["text"].lower()
        assert "posthog again" in mock_client.chat_postMessage.call_args.kwargs["text"].lower()

    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_terminate_action_starts_temporal_workflow(self, mock_config, mock_sync_connect, mock_asyncio_run):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}

        payload = {
            "type": "block_actions",
            "user": {"id": "U123"},
            "actions": [
                {
                    "action_id": "posthog_code_terminate_task",
                    "value": json.dumps(
                        {
                            "run_id": "run-1",
                            "integration_id": self.posthog_code_integration.id,
                            "mentioning_slack_user_id": "U123",
                        }
                    ),
                }
            ],
            "channel": {"id": "C001"},
            "message": {"ts": "1234.9999"},
        }
        response = self._post_interactivity(payload)
        assert response.status_code == 200
        mock_sync_connect.assert_called_once()
        mock_sync_connect.return_value.start_workflow.assert_called_once()
        mock_asyncio_run.assert_called_once()

    @patch("products.tasks.backend.facade.api.send_cancel")
    @patch("products.tasks.backend.facade.api.get_task_run")
    @patch("posthog.models.integration.Integration")
    @patch("posthog.models.integration.SlackIntegration")
    @patch("posthog.temporal.common.client.sync_connect")
    def test_terminate_action_signals_workflow(
        self, mock_sync_connect, mock_slack_integration, mock_integration_model, mock_get_task_run, mock_send_cancel
    ):
        from products.slack_app.backend.tasks import process_posthog_code_task_termination

        mock_send_cancel.return_value = SimpleNamespace(
            success=False, status_code=502, error="Connection refused", retryable=True
        )

        mock_get_task_run.return_value = SimpleNamespace(
            id="run-1",
            task_id="task-1",
            team_id=self.team.id,
            status="in_progress",
            is_terminal=False,
            workflow_id="task-processing-task-1-run-1",
            created_by_id=None,
            created_by_distinct_id=None,
            state={"sandbox_url": "https://sandbox.example.com/rpc"},
        )

        mock_integration = MagicMock()
        mock_integration.team_id = self.team.id
        mock_integration_model.objects.get.return_value = mock_integration

        mock_handle = MagicMock()
        mock_handle.signal = AsyncMock()
        mock_client = MagicMock()
        mock_client.get_workflow_handle.return_value = mock_handle
        mock_sync_connect.return_value = mock_client

        mock_slack_client = MagicMock()
        mock_slack_integration.return_value.client = mock_slack_client

        payload = {
            "type": "block_actions",
            "team": {"id": "T12345"},
            "user": {"id": "U123"},
            "actions": [
                {
                    "action_id": "posthog_code_terminate_task",
                    "value": json.dumps(
                        {
                            "run_id": "run-1",
                            "integration_id": self.posthog_code_integration.id,
                            "mentioning_slack_user_id": "U123",
                        }
                    ),
                }
            ],
            "channel": {"id": "C001"},
            "message": {"ts": "1234.9999"},
        }

        process_posthog_code_task_termination(payload)

        mock_send_cancel.assert_called_once()
        mock_client.get_workflow_handle.assert_called_once_with("task-processing-task-1-run-1")
        mock_handle.signal.assert_called_once()
        mock_slack_client.chat_update.assert_called_once()

    @patch("products.tasks.backend.facade.api.get_task_run")
    @patch("posthog.models.integration.Integration")
    @patch("posthog.models.integration.SlackIntegration")
    @patch("posthog.temporal.common.client.sync_connect")
    def test_terminate_action_without_expected_user_is_denied(
        self, mock_sync_connect, mock_slack_integration, mock_integration_model, mock_get_task_run
    ):
        from products.slack_app.backend.tasks import process_posthog_code_task_termination

        payload = {
            "type": "block_actions",
            "team": {"id": "T12345"},
            "user": {"id": "U123"},
            "actions": [
                {
                    "action_id": "posthog_code_terminate_task",
                    "value": json.dumps(
                        {
                            "run_id": "run-1",
                            "integration_id": self.posthog_code_integration.id,
                        }
                    ),
                }
            ],
            "channel": {"id": "C001"},
            "message": {"ts": "1234.9999"},
        }

        process_posthog_code_task_termination(payload)

        mock_integration_model.objects.get.assert_not_called()
        mock_get_task_run.assert_not_called()
        mock_sync_connect.assert_not_called()
        mock_slack_integration.assert_not_called()

    @patch("products.tasks.backend.facade.api.get_task_run")
    @patch("posthog.models.integration.Integration")
    @patch("posthog.models.integration.SlackIntegration")
    @patch("posthog.temporal.common.client.sync_connect")
    def test_terminate_action_on_terminal_run_posts_feedback(
        self, mock_sync_connect, mock_slack_integration, mock_integration_model, mock_get_task_run
    ):
        from products.slack_app.backend.tasks import process_posthog_code_task_termination

        mock_get_task_run.return_value = SimpleNamespace(
            id="run-1",
            task_id="task-1",
            team_id=self.team.id,
            status="completed",
            is_terminal=True,
            created_by_id=None,
            created_by_distinct_id=None,
        )

        mock_integration = MagicMock()
        mock_integration.team_id = self.team.id
        mock_integration_model.objects.get.return_value = mock_integration
        mock_slack_client = MagicMock()
        mock_slack_integration.return_value.client = mock_slack_client

        payload = {
            "type": "block_actions",
            "team": {"id": "T12345"},
            "user": {"id": "U123"},
            "actions": [
                {
                    "action_id": "posthog_code_terminate_task",
                    "value": json.dumps(
                        {
                            "run_id": "run-1",
                            "integration_id": self.posthog_code_integration.id,
                            "mentioning_slack_user_id": "U123",
                            "thread_ts": "1234.5678",
                        }
                    ),
                }
            ],
            "channel": {"id": "C001"},
            "message": {"ts": "1234.9999"},
        }

        process_posthog_code_task_termination(payload)

        mock_sync_connect.assert_not_called()
        mock_slack_client.chat_postMessage.assert_called_once()

    @patch("products.tasks.backend.facade.api.get_task_run")
    @patch("posthog.models.integration.Integration")
    @patch("posthog.models.integration.SlackIntegration")
    @patch("posthog.temporal.common.client.sync_connect")
    def test_terminate_action_with_mismatched_team_run_is_noop(
        self, mock_sync_connect, mock_slack_integration, mock_integration_model, mock_get_task_run
    ):
        from products.slack_app.backend.tasks import process_posthog_code_task_termination

        # Team-scoped lookup returns nothing when the run belongs to another team.
        mock_get_task_run.return_value = None

        mock_integration = MagicMock()
        mock_integration.team_id = self.team.id
        mock_integration_model.objects.get.return_value = mock_integration
        mock_slack_client = MagicMock()
        mock_slack_integration.return_value.client = mock_slack_client

        payload = {
            "type": "block_actions",
            "team": {"id": "T12345"},
            "user": {"id": "U123"},
            "actions": [
                {
                    "action_id": "posthog_code_terminate_task",
                    "value": json.dumps(
                        {
                            "run_id": "run-1",
                            "integration_id": self.posthog_code_integration.id,
                            "mentioning_slack_user_id": "U123",
                            "thread_ts": "1234.5678",
                        }
                    ),
                }
            ],
            "channel": {"id": "C001"},
            "message": {"ts": "1234.9999"},
        }

        process_posthog_code_task_termination(payload)

        mock_sync_connect.assert_not_called()
        mock_slack_client.chat_postMessage.assert_not_called()


@override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
class TestInteractivityRegionRouting(TestCase):
    """Region-aware proxying for /slack/interactivity-callback.

    The handler accepts interactivity from whichever region Slack delivers to and either handles
    locally or forwards once to the other region. Unlike event-callback, no cross-region lookup
    is involved — the payload's integration_id uniquely identifies the owning row.
    """

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.signing_secret = "posthog-code-test-secret"
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.posthog_code_integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-posthog-code-test"},
        )

    def _post(self, payload: dict, *, host: str = "us.posthog.com", **extra_headers) -> Any:
        payload = {"team": {"id": "T12345"}, **payload}
        body_str = f"payload={json.dumps(payload)}"
        body = body_str.encode()
        signature, ts = sign_slack_request(body, self.signing_secret)
        return self.client.post(
            "/slack/interactivity-callback/",
            data=body_str,
            content_type="application/x-www-form-urlencoded",
            HTTP_HOST=host,
            HTTP_X_SLACK_SIGNATURE=signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
            **extra_headers,
        )

    def _local_picker_payload(self) -> dict:
        # block_id "posthog_code_repo_picker_v1:<token>" + a cached context that points at our
        # local integration is the simplest way to drive the "local" branch in the handler.
        token = "ctx-local-1"
        cache.set(
            f"posthog_code_repo_picker_ctx:{token}",
            {
                "integration_id": self.posthog_code_integration.id,
                "channel": "C001",
                "thread_ts": "1234.5678",
                "user_message_ts": "1234.5678",
                "mentioning_slack_user_id": "U123",
                "event_text": "fix the bug",
                "created_at": int(time.time()),
            },
            timeout=900,
        )
        return {
            "type": "block_suggestion",
            "action_id": "posthog_code_repo_select",
            "value": "",
            "user": {"id": "U123"},
            "block_id": f"posthog_code_repo_picker_v1:{token}",
        }

    def _foreign_picker_payload(self) -> dict:
        # Hints/context point at an integration that is NOT in this DB, so the local check misses.
        return {
            "type": "block_suggestion",
            "action_id": "posthog_code_repo_select",
            "value": "",
            "user": {"id": "U999"},
            "block_id": "posthog_code_repo_picker_v1:no-such-token",
        }

    def _foreign_action_payload(self) -> dict:
        return {
            "type": "block_actions",
            "user": {"id": "U999"},
            "actions": [
                {
                    "action_id": "posthog_code_repo_select",
                    "block_id": "posthog_code_repo_picker_v1:no-such-token",
                    "selected_option": {"value": "posthog/posthog"},
                    "action_ts": "1700000000.123",
                }
            ],
            "message": {"ts": "1234.9999"},
        }

    @staticmethod
    def _proxy_response(status_code: int, content: bytes = b"", content_type: str = "application/json") -> MagicMock:
        upstream = MagicMock()
        upstream.status_code = status_code
        upstream.content = content
        upstream.headers = {"Content-Type": content_type}
        return upstream

    @patch("products.slack_app.backend.api._proxy_event_to_region")
    @patch("products.slack_app.backend.api._get_full_repo_names", return_value=["posthog/posthog"])
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_local_match_handles_without_proxy(self, mock_config, _mock_repos, mock_proxy):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        response = self._post(self._local_picker_payload(), host="us.posthog.com")
        assert response.status_code == 200
        mock_proxy.assert_not_called()

    @patch("products.slack_app.backend.api._proxy_event_to_region")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_us_no_local_proxies_to_eu(self, mock_config, mock_proxy):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_proxy.return_value = self._proxy_response(200, b'{"forwarded": true}')

        response = self._post(self._foreign_picker_payload(), host="us.posthog.com")

        assert response.status_code == 200
        assert response.content == b'{"forwarded": true}'
        mock_proxy.assert_called_once()
        assert mock_proxy.call_args.args[1] == "eu.posthog.com"

    @patch("products.slack_app.backend.api._proxy_event_to_region")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_eu_no_local_proxies_to_us(self, mock_config, mock_proxy):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_proxy.return_value = self._proxy_response(200, b'{"forwarded": true}')

        response = self._post(self._foreign_picker_payload(), host="eu.posthog.com")

        assert response.status_code == 200
        mock_proxy.assert_called_once()
        assert mock_proxy.call_args.args[1] == "us.posthog.com"

    @patch("products.slack_app.backend.api._proxy_event_to_region")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_loop_header_skips_proxy_block_suggestion_returns_empty_options(self, mock_config, mock_proxy):
        # The loop header is what guarantees at-most-one hop. If we receive a payload that we
        # don't own AND the header is set, the other region already deferred — there is no
        # second region to try, so we must return Slack-safe defaults instead of proxying.
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}

        response = self._post(
            self._foreign_picker_payload(),
            host="eu.posthog.com",
            headers={"x-posthog-region-proxied": "1"},
        )

        assert response.status_code == 200
        assert response.json() == {"options": []}
        mock_proxy.assert_not_called()

    @patch("products.slack_app.backend.api._proxy_event_to_region")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_loop_header_skips_proxy_block_actions_returns_200(self, mock_config, mock_proxy):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}

        response = self._post(
            self._foreign_action_payload(),
            host="eu.posthog.com",
            headers={"x-posthog-region-proxied": "1"},
        )

        assert response.status_code == 200
        mock_proxy.assert_not_called()

    @patch("products.slack_app.backend.api._proxy_event_to_region")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_proxy_failure_returns_502_for_actions(self, mock_config, mock_proxy):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_proxy.return_value = None

        response = self._post(self._foreign_action_payload(), host="us.posthog.com")

        assert response.status_code == 502
        mock_proxy.assert_called_once()

    @patch("products.slack_app.backend.api._proxy_event_to_region")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_proxy_failure_returns_empty_options_for_suggestion(self, mock_config, mock_proxy):
        # block_suggestion has a tight render budget on Slack's side; a 502 would surface as a
        # spinner-then-error in the dropdown. Empty options keeps the UI responsive instead.
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_proxy.return_value = None

        response = self._post(self._foreign_picker_payload(), host="us.posthog.com")

        assert response.status_code == 200
        assert response.json() == {"options": []}
        mock_proxy.assert_called_once()

    @patch("products.slack_app.backend.api._proxy_event_to_region")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_proxy_relays_content_type_verbatim(self, mock_config, mock_proxy):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_proxy.return_value = self._proxy_response(201, b"<xml/>", content_type="application/xml")

        response = self._post(self._foreign_picker_payload(), host="us.posthog.com")

        assert response.status_code == 201
        assert response["Content-Type"] == "application/xml"
        assert response.content == b"<xml/>"

    @patch("products.slack_app.backend.api._proxy_event_to_region")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_terminate_hints_local_handles(self, mock_config, mock_sync_connect, _mock_asyncio_run, mock_proxy):
        # Terminate buttons embed integration_id in the action value (not context_token). When
        # the value points at a row in this DB, we must handle locally without consulting the
        # other region — even when the loop header is absent.
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}

        payload = {
            "type": "block_actions",
            "user": {"id": "U123"},
            "actions": [
                {
                    "action_id": "posthog_code_terminate_task",
                    "value": json.dumps(
                        {
                            "run_id": "run-1",
                            "integration_id": self.posthog_code_integration.id,
                            "mentioning_slack_user_id": "U123",
                        }
                    ),
                }
            ],
            "channel": {"id": "C001"},
            "message": {"ts": "1234.9999"},
        }

        response = self._post(payload, host="us.posthog.com")

        assert response.status_code == 200
        mock_proxy.assert_not_called()
        mock_sync_connect.assert_called_once()
        mock_sync_connect.return_value.start_workflow.assert_called_once()


class TestSignalsDismissReport(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signing_secret = "posthog-code-test-secret"

        self.organization = Organization.objects.create(name="Dismiss Org")
        self.team = Team.objects.create(organization=self.organization, name="Dismiss Team")
        self.user = User.objects.create(email="dismisser@example.com", distinct_id="dismiss-user-1")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-test"},
        )

    def _make_ready_report(self):
        from products.signals.backend.models import SignalReport

        return SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Dismissable report",
            summary="Summary",
            signal_count=1,
            total_weight=1.0,
        )

    def _dismiss_payload(self, report_id: str, *, team_id: int | None = None) -> dict:
        return {
            "type": "block_actions",
            "team": {"id": "T12345"},
            "user": {"id": "U777"},
            "response_url": "https://hooks.slack.test/response",
            "actions": [
                {
                    "action_id": "signals_dismiss_report",
                    "value": json.dumps(
                        {
                            "integration_id": self.integration.id,
                            "report_id": report_id,
                            "team_id": team_id if team_id is not None else self.team.id,
                        }
                    ),
                }
            ],
            "message": {"ts": "1234.9999", "blocks": []},
        }

    def _post_interactivity(self, payload: dict) -> Any:
        body_str = f"payload={json.dumps(payload)}"
        signature, ts = sign_slack_request(body_str.encode(), self.signing_secret)
        return self.client.post(
            "/slack/interactivity-callback/",
            data=body_str,
            content_type="application/x-www-form-urlencoded",
            HTTP_X_SLACK_SIGNATURE=signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
        )

    @patch("products.slack_app.backend.api._is_org_member")
    @patch("products.slack_app.backend.api.requests.post")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_dismiss_suppresses_report_and_writes_artefact(self, mock_config, mock_requests_post, mock_is_org_member):
        from products.signals.backend.models import SignalReport, SignalReportArtefact

        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_is_org_member.return_value = self.user  # clicker resolves to this org member
        report = self._make_ready_report()

        response = self._post_interactivity(self._dismiss_payload(str(report.id)))

        assert response.status_code == 200
        report.refresh_from_db()
        assert report.status == SignalReport.Status.SUPPRESSED
        dismissal = SignalReportArtefact.objects.get(report=report, type=SignalReportArtefact.ArtefactType.DISMISSAL)
        # Attributed to the resolved PostHog user, not system.
        assert dismissal.created_by_id == self.user.id
        # The original message is replaced with a dismissed acknowledgement.
        assert mock_requests_post.call_args.kwargs["json"]["replace_original"] is True

    @patch("products.slack_app.backend.api._is_org_member")
    @patch("products.slack_app.backend.api.requests.post")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_dismiss_refuses_non_org_member(self, mock_config, mock_requests_post, mock_is_org_member):
        from products.signals.backend.models import SignalReport

        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_is_org_member.return_value = None  # clicker is not a PostHog org member
        report = self._make_ready_report()

        response = self._post_interactivity(self._dismiss_payload(str(report.id)))

        assert response.status_code == 200
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY  # not suppressed

    @patch("products.slack_app.backend.api.requests.post")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_dismiss_ignores_report_from_another_team(self, mock_config, mock_requests_post):
        from products.signals.backend.models import SignalReport

        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        report = self._make_ready_report()

        # team_id in the button value doesn't match the integration's team.
        response = self._post_interactivity(self._dismiss_payload(str(report.id), team_id=self.team.id + 9999))

        assert response.status_code == 200
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY
