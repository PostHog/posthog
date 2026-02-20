import hmac
import json
import time
import hashlib

from unittest.mock import MagicMock, patch

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


class TestTwigEventHandler(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signing_secret = "twig-test-secret"

    def _post_event(self, payload: dict) -> object:
        body = json.dumps(payload).encode()
        signature, ts = _sign_request(body, self.signing_secret)
        return self.client.post(
            "/slack/twig-event-callback/",
            data=body,
            content_type="application/json",
            HTTP_X_SLACK_SIGNATURE=signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
        )

    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_url_verification(self, mock_config):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}
        response = self._post_event({"type": "url_verification", "challenge": "test-challenge-123"})
        assert response.status_code == 200
        assert response.json() == {"challenge": "test-challenge-123"}

    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_invalid_signature(self, mock_config):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": "different-secret"}
        response = self._post_event({"type": "url_verification", "challenge": "test"})
        assert response.status_code == 403

    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_retry_returns_200(self, mock_config):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}
        body = json.dumps({"type": "event_callback", "event": {"type": "app_mention"}}).encode()
        signature, ts = _sign_request(body, self.signing_secret)
        response = self.client.post(
            "/slack/twig-event-callback/",
            data=body,
            content_type="application/json",
            HTTP_X_SLACK_SIGNATURE=signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
            HTTP_X_SLACK_RETRY_NUM="1",
        )
        assert response.status_code == 200

    @patch("products.slack_app.backend.api.route_twig_event_to_relevant_region")
    @patch("products.slack_app.backend.api.SlackIntegration.twig_slack_config")
    def test_event_callback_routes(self, mock_config, mock_route):
        mock_config.return_value = {"SLACK_TWIG_SIGNING_SECRET": self.signing_secret}
        payload = {
            "type": "event_callback",
            "team_id": "T12345",
            "event": {"type": "app_mention", "text": "hello", "channel": "C001", "user": "U123", "ts": "1234.5678"},
        }
        response = self._post_event(payload)
        assert response.status_code == 202
        mock_route.assert_called_once()

    def test_method_not_allowed(self):
        response = self.client.get("/slack/twig-event-callback/")
        assert response.status_code == 405


class TestHandleTwigAppMention(TestCase):
    def setUp(self):
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

    def _make_event(self, text: str = "<@UBOT> fix the bug", thread_ts: str | None = None) -> dict:
        event = {
            "type": "app_mention",
            "channel": "C001",
            "user": "U123",
            "text": text,
            "ts": "1234.5678",
        }
        if thread_ts:
            event["thread_ts"] = thread_ts
        return event

    @patch("products.slack_app.backend.api.Task")
    @patch("products.slack_app.backend.api.guess_repository")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_single_repo_creates_task(self, mock_webclient_class, mock_resolve, mock_guess, mock_task_class):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.auth_test.return_value = {"bot_id": "B001", "user_id": "UBOT"}
        mock_client.conversations_replies.return_value = {
            "messages": [{"user": "U123", "text": "<@UBOT> fix the bug in posthog-js", "ts": "1234.5678"}]
        }

        from products.slack_app.backend.api import SlackUserContext

        mock_resolve.return_value = SlackUserContext(user=self.user, slack_email="dev@example.com")
        mock_guess.return_value = ["posthog/posthog-js"]

        from products.slack_app.backend.api import handle_twig_app_mention

        handle_twig_app_mention(self._make_event(), self.twig_integration)

        mock_task_class.create_and_run.assert_called_once()
        call_kwargs = mock_task_class.create_and_run.call_args.kwargs
        assert call_kwargs["repository"] == "posthog/posthog-js"
        assert call_kwargs["origin_product"] == mock_task_class.OriginProduct.SLACK
        assert call_kwargs["slack_thread_context"] is not None

    @patch("products.slack_app.backend.api.guess_repository")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_ambiguous_repo_asks_for_clarification(self, mock_webclient_class, mock_resolve, mock_guess):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.auth_test.return_value = {"bot_id": "B001", "user_id": "UBOT"}
        mock_client.conversations_replies.return_value = {
            "messages": [{"user": "U123", "text": "fix the bug", "ts": "1234.5678"}]
        }

        from products.slack_app.backend.api import SlackUserContext

        mock_resolve.return_value = SlackUserContext(user=self.user, slack_email="dev@example.com")
        mock_guess.return_value = []

        from products.slack_app.backend.api import handle_twig_app_mention

        handle_twig_app_mention(self._make_event(), self.twig_integration)

        mock_client.chat_postMessage.assert_called_once()
        call_text = mock_client.chat_postMessage.call_args.kwargs["text"]
        assert "couldn't determine" in call_text.lower()

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.WebClient")
    def test_auth_failure_returns_early(self, mock_webclient_class, mock_resolve):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_resolve.return_value = None

        from products.slack_app.backend.api import handle_twig_app_mention

        handle_twig_app_mention(self._make_event(), self.twig_integration)

        mock_client.auth_test.assert_not_called()
