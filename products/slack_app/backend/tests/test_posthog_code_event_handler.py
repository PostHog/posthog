import hmac
import json
import time
import hashlib
from typing import Any

from unittest.mock import patch

from django.test import TestCase, override_settings
from django.test.client import RequestFactory

from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team


def _sign_request(body: bytes, secret: str) -> tuple[str, str]:
    ts = str(int(time.time()))
    sig_basestring = f"v0:{ts}:{body.decode('utf-8')}"
    signature = "v0=" + hmac.new(secret.encode(), sig_basestring.encode(), hashlib.sha256).hexdigest()
    return signature, ts


class TestPostHogCodeEventHandler(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signing_secret = "posthog-code-test-secret"

    def _post_event(self, payload: dict, **extra_headers) -> Any:
        body = json.dumps(payload).encode()
        signature, ts = _sign_request(body, self.signing_secret)
        return self.client.post(
            "/slack/posthog-code-event-callback/",
            data=body,
            content_type="application/json",
            HTTP_X_SLACK_SIGNATURE=signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
            **extra_headers,
        )

    @patch("products.slack_app.backend.api.SlackIntegration.posthog_code_slack_config")
    def test_url_verification(self, mock_config):
        mock_config.return_value = {"SLACK_POSTHOG_CODE_SIGNING_SECRET": self.signing_secret}
        response = self._post_event({"type": "url_verification", "challenge": "test-challenge-123"})
        assert response.status_code == 200
        assert response.json() == {"challenge": "test-challenge-123"}

    @patch("products.slack_app.backend.api.SlackIntegration.posthog_code_slack_config")
    def test_invalid_signature(self, mock_config):
        mock_config.return_value = {"SLACK_POSTHOG_CODE_SIGNING_SECRET": "different-secret"}
        response = self._post_event({"type": "url_verification", "challenge": "test"})
        assert response.status_code == 403

    @patch("products.slack_app.backend.api.SlackIntegration.posthog_code_slack_config")
    def test_retry_returns_200(self, mock_config):
        mock_config.return_value = {"SLACK_POSTHOG_CODE_SIGNING_SECRET": self.signing_secret}
        body = json.dumps({"type": "event_callback", "event": {"type": "app_mention"}}).encode()
        signature, ts = _sign_request(body, self.signing_secret)
        response = self.client.post(
            "/slack/posthog-code-event-callback/",
            data=body,
            content_type="application/json",
            HTTP_X_SLACK_SIGNATURE=signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
            HTTP_X_SLACK_RETRY_NUM="1",
        )
        assert response.status_code == 200

    @patch("products.slack_app.backend.api.route_posthog_code_event_to_relevant_region")
    @patch("products.slack_app.backend.api.SlackIntegration.posthog_code_slack_config")
    def test_event_callback_routes(self, mock_config, mock_route):
        mock_config.return_value = {"SLACK_POSTHOG_CODE_SIGNING_SECRET": self.signing_secret}
        mock_route.return_value = "handled_locally"
        payload = {
            "type": "event_callback",
            "team_id": "T12345",
            "event": {"type": "app_mention", "text": "hello", "channel": "C001", "user": "U123", "ts": "1234.5678"},
        }
        response = self._post_event(payload)
        assert response.status_code == 202
        mock_route.assert_called_once()

    def test_method_not_allowed(self):
        response = self.client.get("/slack/posthog-code-event-callback/")
        assert response.status_code == 405

    @patch("products.slack_app.backend.api.route_posthog_code_event_to_relevant_region")
    @patch("products.slack_app.backend.api.SlackIntegration.posthog_code_slack_config")
    def test_non_app_mention_event_is_ignored(self, mock_config, mock_route):
        mock_config.return_value = {"SLACK_POSTHOG_CODE_SIGNING_SECRET": self.signing_secret}
        payload = {
            "type": "event_callback",
            "team_id": "T12345",
            "event": {"type": "message", "text": "hello", "channel": "C001", "user": "U123", "ts": "1234.5678"},
        }
        response = self._post_event(payload)
        assert response.status_code == 202
        mock_route.assert_not_called()

    @patch("products.slack_app.backend.api.route_posthog_code_event_to_relevant_region")
    @patch("products.slack_app.backend.api.SlackIntegration.posthog_code_slack_config")
    def test_proxy_failure_returns_502(self, mock_config, mock_route):
        mock_config.return_value = {"SLACK_POSTHOG_CODE_SIGNING_SECRET": self.signing_secret}
        mock_route.return_value = "proxy_failed"
        payload = {
            "type": "event_callback",
            "team_id": "T12345",
            "event": {"type": "app_mention", "text": "hello", "channel": "C001", "user": "U123", "ts": "1234.5678"},
        }
        response = self._post_event(payload)
        assert response.status_code == 502

    @patch("products.slack_app.backend.api.route_posthog_code_event_to_relevant_region")
    @patch("products.slack_app.backend.api.SlackIntegration.posthog_code_slack_config")
    def test_no_integration_still_returns_202(self, mock_config, mock_route):
        mock_config.return_value = {"SLACK_POSTHOG_CODE_SIGNING_SECRET": self.signing_secret}
        mock_route.return_value = "no_integration"
        payload = {
            "type": "event_callback",
            "team_id": "T_UNKNOWN",
            "event": {"type": "app_mention", "text": "hello", "channel": "C001", "user": "U123", "ts": "1234.5678"},
        }
        response = self._post_event(payload)
        assert response.status_code == 202


class TestRoutePostHogCodeEventToRelevantRegion(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.posthog_code_integration = Integration.objects.create(
            team=self.team,
            kind="slack-posthog-code",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-posthog-code-test"},
        )
        self.event = {"type": "app_mention", "channel": "C001", "user": "U123", "ts": "1234.5678"}

    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_local_match_starts_temporal_workflow(self, mock_sync_connect, mock_asyncio_run):
        request = self.factory.post("/slack/posthog-code-event-callback/", HTTP_HOST="eu.posthog.com")

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_sync_connect.assert_called_once()
        mock_sync_connect.return_value.start_workflow.assert_called_once()
        mock_asyncio_run.assert_called_once()

    @patch("products.slack_app.backend.api.proxy_slack_event_to_secondary_region")
    @patch("products.slack_app.backend.api.SLACK_PRIMARY_REGION_DOMAIN", "eu.posthog.com")
    @override_settings(DEBUG=False)
    def test_proxies_to_secondary_when_no_integration_in_primary(self, mock_proxy):
        mock_proxy.return_value = True
        request = self.factory.post("/slack/posthog-code-event-callback/", HTTP_HOST="eu.posthog.com")

        from products.slack_app.backend.api import ROUTE_PROXIED, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T_UNKNOWN")

        assert result == ROUTE_PROXIED
        mock_proxy.assert_called_once_with(request)

    @patch("products.slack_app.backend.api.proxy_slack_event_to_secondary_region")
    @patch("products.slack_app.backend.api.SLACK_PRIMARY_REGION_DOMAIN", "eu.posthog.com")
    @override_settings(DEBUG=False)
    def test_proxy_failure_returns_proxy_failed(self, mock_proxy):
        mock_proxy.return_value = False
        request = self.factory.post("/slack/posthog-code-event-callback/", HTTP_HOST="eu.posthog.com")

        from products.slack_app.backend.api import ROUTE_PROXY_FAILED, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T_UNKNOWN")

        assert result == ROUTE_PROXY_FAILED

    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @patch("products.slack_app.backend.api.proxy_slack_event_to_secondary_region")
    @override_settings(DEBUG=False)
    def test_no_integration_in_secondary_returns_no_integration(self, mock_proxy, mock_sync_connect, mock_asyncio_run):
        request = self.factory.post("/slack/posthog-code-event-callback/", HTTP_HOST="us.posthog.com")

        from products.slack_app.backend.api import ROUTE_NO_INTEGRATION, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T_UNKNOWN")

        assert result == ROUTE_NO_INTEGRATION
        mock_sync_connect.assert_not_called()
        mock_asyncio_run.assert_not_called()
        mock_proxy.assert_not_called()
