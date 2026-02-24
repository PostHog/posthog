import hmac
import json
import time
import hashlib

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User


def _sign_request(body: bytes, secret: str) -> tuple[str, str]:
    ts = str(int(time.time()))
    sig_basestring = f"v0:{ts}:{body.decode('utf-8')}"
    signature = "v0=" + hmac.new(secret.encode(), sig_basestring.encode(), hashlib.sha256).hexdigest()
    return signature, ts


class TestTwigInteractivityHandler(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signing_secret = "twig-test-secret"

    def _post_interactivity(self, payload: dict, **extra_headers) -> object:
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

    def _post_interactivity(self, payload: dict) -> object:
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

    @patch("products.slack_app.backend.tasks.process_twig_repo_selection.delay")
    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_submit_dispatches_celery_task(self, mock_config, mock_delay):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}

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
        mock_delay.assert_called_once_with(payload)


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
    ) -> dict:
        token = context_token or self.context_token
        return {
            "type": "block_actions",
            "user": {"id": user_id},
            "actions": [
                {
                    "action_id": "twig_repo_select",
                    "block_id": f"twig_repo_picker_v1:{token}",
                    "selected_option": {"value": repo},
                    "action_ts": action_ts,
                }
            ],
            "message": {"ts": "1234.9999"},
        }

    @patch("products.slack_app.backend.api._create_task_for_repo")
    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_valid_selection_creates_task(self, mock_webclient_class, mock_resolve, mock_get_repos, mock_create_task):
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

        process_twig_repo_selection(self._make_payload())

        mock_create_task.assert_called_once()
        assert mock_create_task.call_args.kwargs["repository"] == "posthog/posthog"
        mock_client.chat_update.assert_called_once()

    @patch("products.slack_app.backend.api._create_task_for_repo")
    @patch("products.slack_app.backend.api._get_full_repo_names")
    def test_user_mismatch_rejected(self, mock_get_repos, mock_create_task):
        mock_get_repos.return_value = ["posthog/posthog"]

        from products.slack_app.backend.tasks import process_twig_repo_selection

        process_twig_repo_selection(self._make_payload(user_id="U_WRONG"))

        mock_create_task.assert_not_called()

    @patch("products.slack_app.backend.api._create_task_for_repo")
    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("posthog.models.integration.WebClient")
    def test_invalid_repo_rejected(self, mock_webclient_class, mock_get_repos, mock_create_task):
        mock_get_repos.return_value = ["posthog/posthog", "posthog/posthog-js"]

        from products.slack_app.backend.tasks import process_twig_repo_selection

        process_twig_repo_selection(self._make_payload(repo="posthog/nonexistent"))

        mock_create_task.assert_not_called()

    @patch("products.slack_app.backend.api._create_task_for_repo")
    def test_expired_token_is_noop(self, mock_create_task):
        cache.delete(f"twig_repo_picker_ctx:{self.context_token}")

        from products.slack_app.backend.tasks import process_twig_repo_selection

        process_twig_repo_selection(self._make_payload())

        mock_create_task.assert_not_called()

    @patch("products.slack_app.backend.api._create_task_for_repo")
    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_duplicate_submit_is_noop(self, mock_webclient_class, mock_resolve, mock_get_repos, mock_create_task):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.auth_test.return_value = {"bot_id": "B001"}
        mock_client.conversations_replies.return_value = {
            "messages": [{"user": "U123", "text": "fix the bug", "ts": "1234.5678"}]
        }
        mock_get_repos.return_value = ["posthog/posthog"]

        from products.slack_app.backend.api import SlackUserContext

        mock_resolve.return_value = SlackUserContext(user=self.user, slack_email="dev@example.com")

        from products.slack_app.backend.tasks import process_twig_repo_selection

        payload = self._make_payload()
        process_twig_repo_selection(payload)
        mock_create_task.assert_called_once()

        mock_create_task.reset_mock()
        process_twig_repo_selection(payload)
        mock_create_task.assert_not_called()
