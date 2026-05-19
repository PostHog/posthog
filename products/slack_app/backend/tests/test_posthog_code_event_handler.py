import json
from typing import Any

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.test.client import RequestFactory

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.tests.helpers import sign_slack_request


class TestPostHogCodeEventHandler(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signing_secret = "posthog-code-test-secret"

    def _post_event(self, payload: dict, **extra_headers) -> Any:
        body = json.dumps(payload).encode()
        signature, ts = sign_slack_request(body, self.signing_secret)
        return self.client.post(
            "/slack/event-callback/",
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
        signature, ts = sign_slack_request(body, self.signing_secret)
        response = self.client.post(
            "/slack/event-callback/",
            data=body,
            content_type="application/json",
            headers={"x-slack-signature": signature, "x-slack-request-timestamp": ts, "x-slack-retry-num": "1"},
        )
        assert response.status_code == 200

    def test_method_not_allowed(self):
        response = self.client.get("/slack/event-callback/")
        assert response.status_code == 405

    @parameterized.expand(
        [
            ("app_mention_handled_locally", "app_mention", "handled_locally", 202, True),
            ("app_mention_proxy_failed", "app_mention", "proxy_failed", 502, True),
            ("app_mention_no_integration", "app_mention", "no_integration", 202, True),
            ("non_handled_event_type_skips_routing", "message", "handled_locally", 202, False),
        ]
    )
    @patch("products.slack_app.backend.api.route_posthog_code_event_to_relevant_region")
    @patch("products.slack_app.backend.api.SlackIntegration.posthog_code_slack_config")
    def test_event_callback_dispatch(
        self,
        _name,
        event_type: str,
        route_result: str,
        expected_status: int,
        should_route: bool,
        mock_config,
        mock_route,
    ):
        mock_config.return_value = {"SLACK_POSTHOG_CODE_SIGNING_SECRET": self.signing_secret}
        mock_route.return_value = route_result
        payload = {
            "type": "event_callback",
            "team_id": "T12345",
            "event": {"type": event_type, "text": "hello", "channel": "C001", "user": "U123", "ts": "1234.5678"},
        }
        response = self._post_event(payload)
        assert response.status_code == expected_status
        if should_route:
            mock_route.assert_called_once()
        else:
            mock_route.assert_not_called()


class TestRoutePostHogCodeEventToRelevantRegion(TestCase):
    def setUp(self):
        cache.clear()
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

    @patch("products.slack_app.backend.api._posthog_code_enabled_for_integration", return_value=True)
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_local_match_starts_temporal_workflow(self, mock_sync_connect, mock_asyncio_run, _mock_flag):
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="eu.posthog.com")

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_sync_connect.assert_called_once()
        mock_sync_connect.return_value.start_workflow.assert_called_once()
        mock_asyncio_run.assert_called_once()

    @parameterized.expand(
        [
            (
                "resolves_pending_picker",
                True,
                "<@U_BOT> use posthog/posthog-js",
                ["posthog/posthog", "posthog/posthog-js"],
                False,
                True,
            ),
            (
                "repo_not_in_connected_list_starts_new_workflow",
                True,
                "<@U_BOT> use posthog/unknown-repo",
                ["posthog/posthog", "posthog/posthog-js"],
                True,
                False,
            ),
            (
                "no_pending_picker_starts_new_workflow",
                False,
                "<@U_BOT> use posthog/posthog-js",
                ["posthog/posthog", "posthog/posthog-js"],
                True,
                False,
            ),
        ]
    )
    @patch("products.slack_app.backend.api._get_full_repo_names")
    @patch("products.slack_app.backend.api._posthog_code_enabled_for_integration", return_value=True)
    @patch("products.slack_app.backend.api.SlackIntegration")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_explicit_repo_followup_handling(
        self,
        _name,
        has_pending_picker: bool,
        event_text: str,
        repo_list: list[str],
        expect_new_workflow: bool,
        expect_picker_resolution: bool,
        mock_sync_connect,
        mock_asyncio_run,
        mock_slack_cls,
        _mock_flag,
        mock_get_repos,
    ):
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="eu.posthog.com")
        mock_get_repos.return_value = repo_list

        from products.slack_app.backend.api import (
            ROUTE_HANDLED_LOCALLY,
            _get_pending_repo_picker,
            _set_pending_repo_picker,
            route_posthog_code_event_to_relevant_region,
        )

        if has_pending_picker:
            _set_pending_repo_picker(
                integration_id=self.posthog_code_integration.id,
                channel="C001",
                thread_ts="1234.5678",
                slack_user_id="U123",
                workflow_id="posthog-code-mention-T12345:pending",
                context_token="ctx-1",
                message_ts="1234.7777",
            )
        event = {
            "type": "app_mention",
            "channel": "C001",
            "thread_ts": "1234.5678",
            "user": "U123",
            "text": event_text,
            "ts": "1234.9999",
        }

        result = route_posthog_code_event_to_relevant_region(request, event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_sync_connect.assert_called_once()
        if expect_picker_resolution:
            mock_sync_connect.return_value.get_workflow_handle.assert_called_once_with(
                "posthog-code-mention-T12345:pending"
            )
            mock_sync_connect.return_value.start_workflow.assert_not_called()
            mock_asyncio_run.assert_called_once()
            mock_slack_cls.return_value.client.chat_update.assert_called_once()
        else:
            mock_sync_connect.return_value.get_workflow_handle.assert_not_called()
            mock_sync_connect.return_value.start_workflow.assert_called_once()
            mock_asyncio_run.assert_called_once()
            mock_slack_cls.return_value.client.chat_update.assert_not_called()

        pending_picker = _get_pending_repo_picker(
            integration_id=self.posthog_code_integration.id,
            channel="C001",
            thread_ts="1234.5678",
            slack_user_id="U123",
        )
        if expect_new_workflow:
            if has_pending_picker:
                assert pending_picker is not None
                assert pending_picker["workflow_id"] == "posthog-code-mention-T12345:pending"
            else:
                assert pending_picker is None
        else:
            assert pending_picker is None

    @patch("products.slack_app.backend.api._posthog_code_enabled_for_integration", return_value=False)
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_local_match_flag_off_skips_workflow(self, mock_sync_connect, mock_asyncio_run, _mock_flag):
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="eu.posthog.com")

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_sync_connect.assert_not_called()
        mock_asyncio_run.assert_not_called()

    @patch("products.slack_app.backend.api.handle_posthog_link_unfurl")
    @override_settings(DEBUG=False)
    def test_link_shared_routes_to_unfurl(self, mock_unfurl):
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="eu.posthog.com")
        link_shared_event = {"type": "link_shared", "channel": "C001", "links": []}

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, link_shared_event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_unfurl.assert_called_once()
        passed_integration = mock_unfurl.call_args[0][1]
        assert passed_integration.id == self.posthog_code_integration.id

    @patch("products.slack_app.backend.api.handle_posthog_link_unfurl")
    @override_settings(DEBUG=False)
    def test_link_shared_works_with_only_notifications_integration(self, mock_unfurl):
        # Delete the coding-agent integration and create a notifications-only integration for same workspace
        self.posthog_code_integration.delete()
        Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-notifications"},
        )
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="eu.posthog.com")
        link_shared_event = {"type": "link_shared", "channel": "C001", "links": []}

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, link_shared_event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_unfurl.assert_called_once()
        # Don't assert on which integration row was passed: "first row by id" picking is a known
        # limitation for multi-team workspaces and shouldn't be baked into the test contract.
        passed_integration = mock_unfurl.call_args[0][1]
        assert passed_integration.integration_id == "T12345"

    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @patch("products.slack_app.backend.api.proxy_slack_event_to_secondary_region")
    @patch("products.slack_app.backend.api.SLACK_PRIMARY_REGION_DOMAIN", "eu.posthog.com")
    @override_settings(DEBUG=False)
    def test_app_mention_in_primary_with_only_notifications_proxies_to_secondary(
        self, mock_proxy, mock_sync_connect, mock_asyncio_run
    ):
        # Regression test: the coding-agent install may live in the other region. A notifications-only
        # row in the primary region must NOT short-circuit the proxy path for app_mention.
        self.posthog_code_integration.delete()
        Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-notifications"},
        )
        mock_proxy.return_value = True
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="eu.posthog.com")

        from products.slack_app.backend.api import ROUTE_PROXIED, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345")

        assert result == ROUTE_PROXIED
        mock_proxy.assert_called_once_with(request)
        mock_sync_connect.assert_not_called()
        mock_asyncio_run.assert_not_called()

    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_app_mention_in_secondary_with_only_notifications_noop(self, mock_sync_connect, mock_asyncio_run):
        # In the secondary region with only a notifications install, app_mention should
        # report no_integration (no coding-agent install anywhere reachable from here).
        self.posthog_code_integration.delete()
        Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-notifications"},
        )
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")

        from products.slack_app.backend.api import ROUTE_NO_INTEGRATION, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345")

        assert result == ROUTE_NO_INTEGRATION
        mock_sync_connect.assert_not_called()
        mock_asyncio_run.assert_not_called()

    @patch("products.slack_app.backend.api.proxy_slack_event_to_secondary_region")
    @patch("products.slack_app.backend.api.SLACK_PRIMARY_REGION_DOMAIN", "eu.posthog.com")
    @override_settings(DEBUG=False)
    def test_proxies_to_secondary_when_no_integration_in_primary(self, mock_proxy):
        mock_proxy.return_value = True
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="eu.posthog.com")

        from products.slack_app.backend.api import ROUTE_PROXIED, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T_UNKNOWN")

        assert result == ROUTE_PROXIED
        mock_proxy.assert_called_once_with(request)

    @patch("products.slack_app.backend.api.proxy_slack_event_to_secondary_region")
    @patch("products.slack_app.backend.api.SLACK_PRIMARY_REGION_DOMAIN", "eu.posthog.com")
    @override_settings(DEBUG=False)
    def test_proxy_failure_returns_proxy_failed(self, mock_proxy):
        mock_proxy.return_value = False
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="eu.posthog.com")

        from products.slack_app.backend.api import ROUTE_PROXY_FAILED, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T_UNKNOWN")

        assert result == ROUTE_PROXY_FAILED

    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @patch("products.slack_app.backend.api.proxy_slack_event_to_secondary_region")
    @override_settings(DEBUG=False)
    def test_no_integration_in_secondary_returns_no_integration(self, mock_proxy, mock_sync_connect, mock_asyncio_run):
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")

        from products.slack_app.backend.api import ROUTE_NO_INTEGRATION, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T_UNKNOWN")

        assert result == ROUTE_NO_INTEGRATION
        mock_sync_connect.assert_not_called()
        mock_asyncio_run.assert_not_called()
        mock_proxy.assert_not_called()
