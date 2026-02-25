import hmac
import json
import time
import hashlib
from typing import Any

from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackUserRepoPreference


def _sign_request(body: bytes, secret: str) -> tuple[str, str]:
    ts = str(int(time.time()))
    sig_basestring = f"v0:{ts}:{body.decode('utf-8')}"
    signature = "v0=" + hmac.new(secret.encode(), sig_basestring.encode(), hashlib.sha256).hexdigest()
    return signature, ts


class TestTwigInteractivityHandler(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signing_secret = "twig-test-secret"

    def _post_interactivity(self, payload: dict, **extra_headers) -> Any:
        payload = {"team": {"id": "T12345"}, **payload}
        body_str = f"payload={json.dumps(payload)}"
        body = body_str.encode()
        signature, ts = _sign_request(body, self.signing_secret)
        return self.client.post(
            "/slack/twig-interactivity-callback/",
            data=body_str,
            content_type="application/x-www-form-urlencoded",
            HTTP_X_SLACK_SIGNATURE=signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
            **extra_headers,
        )

    def test_get_method_returns_405(self):
        response = self.client.get("/slack/twig-interactivity-callback/")
        assert response.status_code == 405

    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_invalid_signature_returns_403(self, mock_config):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": "different-secret"}
        response = self._post_interactivity({"type": "block_suggestion"})
        assert response.status_code == 403


class TestRepoPickerOptions(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.signing_secret = "twig-test-secret"

        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-1")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)
        self.twig_integration = Integration.objects.create(
            team=self.team,
            kind="slack-twig",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-twig-test"},
        )
        self.github_integration = Integration.objects.create(
            team=self.team,
            kind="github",
            config={"account": {"name": "posthog"}},
            sensitive_config={"access_token": "ghp-test"},
        )

        self.context_token = "test-token-1234"
        self.context_payload = {
            "integration_id": self.twig_integration.id,
            "channel": "C001",
            "thread_ts": "1234.5678",
            "user_message_ts": "1234.5678",
            "mentioning_slack_user_id": "U123",
            "event_text": "fix the bug",
            "created_at": int(time.time()),
        }
        cache.set(f"twig_repo_picker_ctx:{self.context_token}", self.context_payload, timeout=900)

    def _post_interactivity(self, payload: dict) -> Any:
        payload = {"team": {"id": "T12345"}, **payload}
        body_str = f"payload={json.dumps(payload)}"
        body = body_str.encode()
        signature, ts = _sign_request(body, self.signing_secret)
        return self.client.post(
            "/slack/twig-interactivity-callback/",
            data=body_str,
            content_type="application/x-www-form-urlencoded",
            HTTP_X_SLACK_SIGNATURE=signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
        )

    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_options_returns_filtered_repos(self, mock_config, mock_get_repos):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}
        mock_get_repos.return_value = ["posthog/posthog", "posthog/posthog-js", "posthog/hogvm"]

        payload = {
            "type": "block_suggestion",
            "action_id": "twig_repo_select",
            "value": "js",
            "user": {"id": "U123"},
            "block_id": f"twig_repo_picker_v1:{self.context_token}",
        }
        response = self._post_interactivity(payload)
        assert response.status_code == 200
        options = response.json()["options"]
        assert len(options) == 1
        assert options[0]["value"] == "posthog/posthog-js"

    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_options_empty_query_returns_all(self, mock_config, mock_get_repos):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}
        mock_get_repos.return_value = ["posthog/posthog", "posthog/posthog-js"]

        payload = {
            "type": "block_suggestion",
            "action_id": "twig_repo_select",
            "value": "",
            "user": {"id": "U123"},
            "block_id": f"twig_repo_picker_v1:{self.context_token}",
        }
        response = self._post_interactivity(payload)
        assert response.status_code == 200
        assert len(response.json()["options"]) == 2

    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_options_wrong_user_returns_empty(self, mock_config):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}

        payload = {
            "type": "block_suggestion",
            "action_id": "twig_repo_select",
            "value": "",
            "user": {"id": "U_WRONG"},
            "block_id": f"twig_repo_picker_v1:{self.context_token}",
        }
        response = self._post_interactivity(payload)
        assert response.status_code == 200
        assert response.json()["options"] == []

    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_options_expired_token_returns_empty(self, mock_config):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}
        cache.delete(f"twig_repo_picker_ctx:{self.context_token}")

        payload = {
            "type": "block_suggestion",
            "action_id": "twig_repo_select",
            "value": "",
            "user": {"id": "U123"},
            "block_id": f"twig_repo_picker_v1:{self.context_token}",
        }
        response = self._post_interactivity(payload)
        assert response.status_code == 200
        assert response.json()["options"] == []

    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_submit_signals_temporal_workflow(self, mock_config, mock_sync_connect, mock_asyncio_run):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}
        self.context_payload["workflow_id"] = "twig-mention-T12345:C001:1234.5678"
        cache.set(f"twig_repo_picker_ctx:{self.context_token}", self.context_payload, timeout=900)

        payload = {
            "type": "block_actions",
            "user": {"id": "U123"},
            "actions": [
                {
                    "action_id": "twig_repo_select",
                    "block_id": f"twig_repo_picker_v1:{self.context_token}",
                    "selected_option": {"value": "posthog/posthog"},
                    "action_ts": "1700000000.123",
                }
            ],
            "message": {"ts": "1234.9999"},
        }
        response = self._post_interactivity(payload)
        assert response.status_code == 200
        mock_sync_connect.assert_called_once()
        mock_sync_connect.return_value.get_workflow_handle.assert_called_once_with("twig-mention-T12345:C001:1234.5678")
        mock_asyncio_run.assert_called_once()

    @patch("posthog.models.integration.WebClient")
    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_submit_without_workflow_id_posts_expired(self, mock_config, mock_webclient_class):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        self.context_payload.pop("workflow_id", None)
        cache.set(f"twig_repo_picker_ctx:{self.context_token}", self.context_payload, timeout=900)

        payload = {
            "type": "block_actions",
            "user": {"id": "U123"},
            "actions": [
                {
                    "action_id": "twig_repo_select",
                    "block_id": f"twig_repo_picker_v1:{self.context_token}",
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

    @patch("posthog.models.integration.WebClient")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_submit_signal_failure_posts_expired(
        self,
        mock_config,
        mock_sync_connect,
        mock_asyncio_run,
        mock_webclient_class,
    ):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        self.context_payload["workflow_id"] = "twig-mention-T12345:C001:1234.5678"
        cache.set(f"twig_repo_picker_ctx:{self.context_token}", self.context_payload, timeout=900)
        mock_asyncio_run.side_effect = RuntimeError("workflow not found")

        payload = {
            "type": "block_actions",
            "user": {"id": "U123"},
            "actions": [
                {
                    "action_id": "twig_repo_select",
                    "block_id": f"twig_repo_picker_v1:{self.context_token}",
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

    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_terminate_action_starts_temporal_workflow(self, mock_config, mock_sync_connect, mock_asyncio_run):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}

        payload = {
            "type": "block_actions",
            "user": {"id": "U123"},
            "actions": [
                {
                    "action_id": "twig_terminate_task",
                    "value": json.dumps(
                        {
                            "run_id": "run-1",
                            "integration_id": self.twig_integration.id,
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

    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_default_repo_submit_starts_temporal_workflow(self, mock_config, mock_sync_connect, mock_asyncio_run):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}

        payload = {
            "type": "block_actions",
            "user": {"id": "U123"},
            "actions": [
                {
                    "action_id": "twig_default_repo_select",
                    "block_id": f"twig_repo_picker_v1:{self.context_token}",
                    "selected_option": {"value": "posthog/posthog"},
                    "action_ts": "1700000000.124",
                }
            ],
            "message": {"ts": "1234.9999"},
        }
        response = self._post_interactivity(payload)
        assert response.status_code == 200
        mock_sync_connect.assert_called_once()
        mock_sync_connect.return_value.start_workflow.assert_called_once()
        mock_asyncio_run.assert_called_once()


class TestProcessTwigRepoSelection(TestCase):
    def setUp(self):
        cache.clear()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-1")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)

        self.twig_integration = Integration.objects.create(
            team=self.team,
            kind="slack-twig",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-twig-test"},
        )
        self.github_integration = Integration.objects.create(
            team=self.team,
            kind="github",
            config={"account": {"name": "posthog"}},
            sensitive_config={"access_token": "ghp-test"},
        )

        self.context_token = "test-token-5678"
        self.context_payload = {
            "integration_id": self.twig_integration.id,
            "channel": "C001",
            "thread_ts": "1234.5678",
            "user_message_ts": "1234.5678",
            "mentioning_slack_user_id": "U123",
            "event_text": "fix the bug",
            "created_at": int(time.time()),
        }
        cache.set(f"twig_repo_picker_ctx:{self.context_token}", self.context_payload, timeout=900)

    def _make_payload(
        self,
        *,
        repo: str = "posthog/posthog",
        user_id: str = "U123",
        action_ts: str = "1700000000.123",
        context_token: str | None = None,
        action_id: str = "twig_repo_select",
    ) -> dict:
        token = context_token or self.context_token
        return {
            "type": "block_actions",
            "team": {"id": "T12345"},
            "user": {"id": user_id},
            "actions": [
                {
                    "action_id": action_id,
                    "block_id": f"twig_repo_picker_v1:{token}",
                    "selected_option": {"value": repo},
                    "action_ts": action_ts,
                }
            ],
            "message": {"ts": "1234.9999"},
        }

    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_non_default_action_is_ignored(self, mock_webclient_class, mock_resolve, mock_get_repos):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_get_repos.return_value = ["posthog/posthog", "posthog/posthog-js"]

        from products.slack_app.backend.tasks import process_twig_repo_selection

        process_twig_repo_selection(self._make_payload(action_id="twig_repo_select"))

        mock_resolve.assert_not_called()
        mock_client.chat_update.assert_not_called()
        assert SlackUserRepoPreference.objects.filter(team=self.team, user=self.user, channel="C001").count() == 0

    @patch("products.slack_app.backend.api._get_full_repo_names")
    def test_user_mismatch_rejected(self, mock_get_repos):
        mock_get_repos.return_value = ["posthog/posthog"]

        from products.slack_app.backend.tasks import process_twig_repo_selection

        process_twig_repo_selection(self._make_payload(user_id="U_WRONG", action_id="twig_default_repo_select"))

        assert SlackUserRepoPreference.objects.filter(team=self.team, user=self.user, channel="C001").count() == 0

    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("posthog.models.integration.WebClient")
    def test_invalid_repo_rejected(self, mock_webclient_class, mock_get_repos):
        mock_get_repos.return_value = ["posthog/posthog", "posthog/posthog-js"]

        from products.slack_app.backend.tasks import process_twig_repo_selection

        process_twig_repo_selection(
            self._make_payload(repo="posthog/nonexistent", action_id="twig_default_repo_select")
        )

        assert SlackUserRepoPreference.objects.filter(team=self.team, user=self.user, channel="C001").count() == 0

    def test_expired_token_is_noop(self):
        cache.delete(f"twig_repo_picker_ctx:{self.context_token}")

        from products.slack_app.backend.tasks import process_twig_repo_selection

        process_twig_repo_selection(self._make_payload(action_id="twig_default_repo_select"))

        assert SlackUserRepoPreference.objects.filter(team=self.team, user=self.user, channel="C001").count() == 0

    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_duplicate_submit_is_noop(self, mock_webclient_class, mock_resolve, mock_get_repos):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_get_repos.return_value = ["posthog/posthog"]

        from products.slack_app.backend.api import SlackUserContext

        mock_resolve.return_value = SlackUserContext(user=self.user, slack_email="dev@example.com")

        from products.slack_app.backend.tasks import process_twig_repo_selection

        payload = self._make_payload(action_id="twig_default_repo_select")
        process_twig_repo_selection(payload)
        preference = SlackUserRepoPreference.objects.get(team=self.team, user=self.user, channel="C001")
        assert preference.repository == "posthog/posthog"
        assert mock_client.chat_update.call_count == 1

        mock_client.chat_update.reset_mock()
        process_twig_repo_selection(payload)
        mock_client.chat_update.assert_not_called()

    @patch("products.slack_app.backend.api._create_task_for_repo")
    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_default_repo_selection_sets_preference_without_creating_task(
        self, mock_webclient_class, mock_resolve, mock_get_repos, mock_create_task
    ):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.auth_test.return_value = {"bot_id": "B001"}
        mock_client.conversations_replies.return_value = {
            "messages": [{"user": "U123", "text": "fix the bug", "ts": "1234.5678"}]
        }
        mock_get_repos.return_value = ["posthog/posthog", "posthog/posthog-js"]

        from products.slack_app.backend.api import SlackUserContext

        mock_resolve.return_value = SlackUserContext(user=self.user, slack_email="dev@example.com")

        from products.slack_app.backend.tasks import process_twig_repo_selection

        process_twig_repo_selection(self._make_payload(action_id="twig_default_repo_select", repo="posthog/posthog-js"))

        mock_create_task.assert_not_called()
        preference = SlackUserRepoPreference.objects.get(team=self.team, user=self.user, channel="C001")
        assert preference.repository == "posthog/posthog-js"

    @patch("products.tasks.backend.models.TaskRun")
    @patch("posthog.models.integration.Integration")
    @patch("posthog.models.integration.SlackIntegration")
    @patch("posthog.temporal.common.client.sync_connect")
    def test_terminate_action_signals_workflow(
        self, mock_sync_connect, mock_slack_integration, mock_integration_model, mock_task_run_model
    ):
        from products.slack_app.backend.tasks import process_twig_task_termination

        mock_run = MagicMock()
        mock_run.id = "run-1"
        mock_run.task_id = "task-1"
        mock_run.team_id = self.team.id
        mock_run.status = "in_progress"
        mock_task_run_model.Status.COMPLETED = "completed"
        mock_task_run_model.Status.FAILED = "failed"
        mock_task_run_model.Status.CANCELLED = "cancelled"
        mock_task_run_model.objects.select_related.return_value.get.return_value = mock_run

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
                    "action_id": "twig_terminate_task",
                    "value": json.dumps(
                        {
                            "run_id": "run-1",
                            "integration_id": self.twig_integration.id,
                            "mentioning_slack_user_id": "U123",
                        }
                    ),
                }
            ],
            "channel": {"id": "C001"},
            "message": {"ts": "1234.9999"},
        }

        process_twig_task_termination(payload)

        mock_client.get_workflow_handle.assert_called_once_with("task-processing-task-1-run-1")
        mock_handle.signal.assert_called_once()
        mock_slack_client.chat_update.assert_called_once()

    @patch("products.tasks.backend.models.TaskRun")
    @patch("posthog.models.integration.Integration")
    @patch("posthog.models.integration.SlackIntegration")
    @patch("posthog.temporal.common.client.sync_connect")
    def test_terminate_action_without_expected_user_is_denied(
        self, mock_sync_connect, mock_slack_integration, mock_integration_model, mock_task_run_model
    ):
        from products.slack_app.backend.tasks import process_twig_task_termination

        payload = {
            "type": "block_actions",
            "team": {"id": "T12345"},
            "user": {"id": "U123"},
            "actions": [
                {
                    "action_id": "twig_terminate_task",
                    "value": json.dumps(
                        {
                            "run_id": "run-1",
                            "integration_id": self.twig_integration.id,
                        }
                    ),
                }
            ],
            "channel": {"id": "C001"},
            "message": {"ts": "1234.9999"},
        }

        process_twig_task_termination(payload)

        mock_integration_model.objects.get.assert_not_called()
        mock_task_run_model.objects.select_related.assert_not_called()
        mock_sync_connect.assert_not_called()
        mock_slack_integration.assert_not_called()

    @patch("products.tasks.backend.models.TaskRun")
    @patch("posthog.models.integration.Integration")
    @patch("posthog.models.integration.SlackIntegration")
    @patch("posthog.temporal.common.client.sync_connect")
    def test_terminate_action_on_terminal_run_posts_feedback(
        self, mock_sync_connect, mock_slack_integration, mock_integration_model, mock_task_run_model
    ):
        from products.slack_app.backend.tasks import process_twig_task_termination

        mock_run = MagicMock()
        mock_run.id = "run-1"
        mock_run.task_id = "task-1"
        mock_run.team_id = self.team.id
        mock_run.status = "completed"
        mock_task_run_model.Status.COMPLETED = "completed"
        mock_task_run_model.Status.FAILED = "failed"
        mock_task_run_model.Status.CANCELLED = "cancelled"
        mock_task_run_model.objects.select_related.return_value.get.return_value = mock_run

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
                    "action_id": "twig_terminate_task",
                    "value": json.dumps(
                        {
                            "run_id": "run-1",
                            "integration_id": self.twig_integration.id,
                            "mentioning_slack_user_id": "U123",
                            "thread_ts": "1234.5678",
                        }
                    ),
                }
            ],
            "channel": {"id": "C001"},
            "message": {"ts": "1234.9999"},
        }

        process_twig_task_termination(payload)

        mock_sync_connect.assert_not_called()
        mock_slack_client.chat_postMessage.assert_called_once()

    @patch("products.tasks.backend.models.TaskRun")
    @patch("posthog.models.integration.Integration")
    @patch("posthog.models.integration.SlackIntegration")
    @patch("posthog.temporal.common.client.sync_connect")
    def test_terminate_action_with_mismatched_team_run_is_noop(
        self, mock_sync_connect, mock_slack_integration, mock_integration_model, mock_task_run_model
    ):
        from products.slack_app.backend.tasks import process_twig_task_termination

        mock_task_run_model.DoesNotExist = Exception
        mock_task_run_model.Status.COMPLETED = "completed"
        mock_task_run_model.Status.FAILED = "failed"
        mock_task_run_model.Status.CANCELLED = "cancelled"
        mock_task_run_model.objects.select_related.return_value.get.side_effect = mock_task_run_model.DoesNotExist

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
                    "action_id": "twig_terminate_task",
                    "value": json.dumps(
                        {
                            "run_id": "run-1",
                            "integration_id": self.twig_integration.id,
                            "mentioning_slack_user_id": "U123",
                            "thread_ts": "1234.5678",
                        }
                    ),
                }
            ],
            "channel": {"id": "C001"},
            "message": {"ts": "1234.9999"},
        }

        process_twig_task_termination(payload)

        mock_sync_connect.assert_not_called()
        mock_slack_client.chat_postMessage.assert_not_called()
