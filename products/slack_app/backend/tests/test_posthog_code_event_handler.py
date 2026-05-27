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
        from products.slack_app.backend.api import POSTHOG_CODE_REQUIRED_SLACK_SCOPES

        cache.clear()
        self.factory = RequestFactory()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.posthog_code_integration = Integration.objects.create(
            team=self.team,
            kind="slack-posthog-code",
            integration_id="T12345",
            config={"scope": ",".join(sorted(POSTHOG_CODE_REQUIRED_SLACK_SCOPES))},
            sensitive_config={"access_token": "xoxb-posthog-code-test"},
        )
        self.event = {"type": "app_mention", "channel": "C001", "user": "U123", "ts": "1234.5678"}

    @patch("products.slack_app.backend.api._posthog_code_enabled_for_integration", return_value=True)
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_local_match_starts_temporal_workflow(self, mock_sync_connect, mock_asyncio_run, _mock_flag):
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")

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
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        mock_get_repos.return_value = repo_list
        # The route runs _missing_posthog_code_slack_scopes against a real SlackIntegration
        # before the picker / workflow path. Since SlackIntegration is mocked wholesale here,
        # explicitly say no scopes are missing so the gate passes through.
        mock_slack_cls.return_value.missing_scopes.return_value = frozenset()

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

    @parameterized.expand(
        [
            ("edited_field", {"edited": {"user": "U123", "ts": "1234.7777"}}),
            ("message_changed_subtype", {"subtype": "message_changed"}),
            ("bot_id", {"bot_id": "B0ALERT"}),
            ("bot_profile", {"bot_profile": {"name": "Mendral", "id": "B0ALERT"}}),
            ("app_id", {"app_id": "A0ALERT"}),
            ("bot_message_subtype", {"subtype": "bot_message"}),
            ("slackbot_user", {"user": "USLACKBOT"}),
        ]
    )
    @patch("products.slack_app.backend.api._posthog_code_enabled_for_integration", return_value=True)
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_app_mention_ignored_does_not_start_workflow(
        self,
        _name,
        ignore_marker: dict,
        mock_sync_connect,
        mock_asyncio_run,
        _mock_flag,
    ):
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        ignored_event = {**self.event, **ignore_marker}

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, ignored_event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_sync_connect.assert_not_called()
        mock_asyncio_run.assert_not_called()

    @patch("products.slack_app.backend.api._posthog_code_enabled_for_integration", return_value=True)
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_command_text_routes_to_command_workflow(self, mock_sync_connect, mock_asyncio_run, _mock_flag):
        # Command text in a mention must dispatch the command workflow, never the agent
        # mention workflow — even when a single coding-agent integration exists.
        from posthog.temporal.ai.posthog_code_slack_mention_command import PostHogCodeSlackMentionCommandWorkflow

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        event = {**self.event, "text": "<@UBOT123> project 2"}

        result = route_posthog_code_event_to_relevant_region(request, event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_sync_connect.return_value.start_workflow.assert_called_once()
        kicked_off = mock_sync_connect.return_value.start_workflow.call_args.args[0]
        assert kicked_off == PostHogCodeSlackMentionCommandWorkflow.run
        mock_asyncio_run.assert_called_once()

    @patch("products.slack_app.backend.api._posthog_code_enabled_for_integration", return_value=True)
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_command_workflow_receives_all_workspace_candidates(self, mock_sync_connect, mock_asyncio_run, _mock_flag):
        # When multiple coding-agent integrations exist for the same workspace, all of
        # their IDs must be forwarded to the command workflow so it can handle project
        # commands without the caller having to pre-resolve a single target.
        from posthog.models.team.team import Team

        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_integration = Integration.objects.create(
            team=other_team,
            kind="slack-posthog-code",
            integration_id="T12345",
            config=self.posthog_code_integration.config,
            sensitive_config={"access_token": "xoxb-other"},
        )

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        event = {**self.event, "text": "<@UBOT123> project 2"}

        result = route_posthog_code_event_to_relevant_region(request, event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_sync_connect.return_value.start_workflow.assert_called_once()
        workflow_inputs = mock_sync_connect.return_value.start_workflow.call_args.args[1]
        assert set(workflow_inputs.integration_ids) == {
            self.posthog_code_integration.id,
            other_integration.id,
        }

    @patch("products.slack_app.backend.api._posthog_code_enabled_for_integration", return_value=True)
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_rules_add_without_repo_routes_to_command_workflow_for_picker(
        self, mock_sync_connect, mock_asyncio_run, _mock_flag
    ):
        # ``rules add "description"`` with no inline repo is still a command, so
        # the webhook hands it to the command workflow. The command workflow
        # itself drives the interactive repo picker (its own signal handlers and
        # wait_condition); the agent mention workflow is never involved.
        from posthog.temporal.ai.posthog_code_slack_mention_command import PostHogCodeSlackMentionCommandWorkflow

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        request = self.factory.post("/slack/event-callback/", HTTP_HOST="eu.posthog.com")
        event = {**self.event, "text": '<@UBOT123> rules add "investigate flaky tests"'}

        result = route_posthog_code_event_to_relevant_region(request, event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_sync_connect.return_value.start_workflow.assert_called_once()
        kicked_off = mock_sync_connect.return_value.start_workflow.call_args.args[0]
        assert kicked_off == PostHogCodeSlackMentionCommandWorkflow.run

    @patch("products.slack_app.backend.api._posthog_code_enabled_for_integration", return_value=False)
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_local_match_flag_off_skips_workflow(self, mock_sync_connect, mock_asyncio_run, _mock_flag):
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_sync_connect.assert_not_called()
        mock_asyncio_run.assert_not_called()

    @patch("products.slack_app.backend.api._posthog_code_enabled_for_integration", return_value=False)
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_command_text_with_flag_off_skips_command_workflow(self, mock_sync_connect, mock_asyncio_run, _mock_flag):
        # Command text from an org outside the rollout must not spawn the command
        # workflow either — the whole @PostHog surface is gated, not just the agent.
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        event = {**self.event, "text": "<@UBOT123> help"}

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_sync_connect.assert_not_called()
        mock_asyncio_run.assert_not_called()

    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_partial_flag_enable_filters_candidates(self, mock_sync_connect, mock_asyncio_run):
        # Two integrations in the same workspace, only one in the rollout. The
        # command workflow should receive only the enabled integration's id.
        from posthog.models.team.team import Team

        other_team = Team.objects.create(organization=self.organization, name="Other")
        disabled_integration = Integration.objects.create(
            team=other_team,
            kind="slack-posthog-code",
            integration_id="T12345",
            config=self.posthog_code_integration.config,
            sensitive_config={"access_token": "xoxb-other"},
        )

        enabled_id = self.posthog_code_integration.id

        def flag_for(integration):
            return integration.id == enabled_id

        with patch("products.slack_app.backend.api._posthog_code_enabled_for_integration", side_effect=flag_for):
            from products.slack_app.backend.api import (
                ROUTE_HANDLED_LOCALLY,
                route_posthog_code_event_to_relevant_region,
            )

            request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
            event = {**self.event, "text": "<@UBOT123> help"}

            result = route_posthog_code_event_to_relevant_region(request, event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_sync_connect.return_value.start_workflow.assert_called_once()
        workflow_inputs = mock_sync_connect.return_value.start_workflow.call_args.args[1]
        assert workflow_inputs.integration_ids == [enabled_id]
        assert disabled_integration.id not in workflow_inputs.integration_ids

    @patch("products.slack_app.backend.api.handle_posthog_link_unfurl")
    @override_settings(DEBUG=False)
    def test_link_shared_routes_to_unfurl(self, mock_unfurl):
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
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
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        link_shared_event = {"type": "link_shared", "channel": "C001", "links": []}

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, link_shared_event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_unfurl.assert_called_once()
        # Don't assert on which integration row was passed: "first row by id" picking is a known
        # limitation for multi-team workspaces and shouldn't be baked into the test contract.
        passed_integration = mock_unfurl.call_args[0][1]
        assert passed_integration.integration_id == "T12345"

    @patch("products.slack_app.backend.api._proxy_event_and_return_route")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_app_mention_on_us_with_only_notifications_proxies_to_eu(
        self, mock_sync_connect, mock_asyncio_run, mock_proxy
    ):
        # US (primary) holds only a notifications install. The coding-agent install may live in EU,
        # so the event must be proxied without consulting the lookup endpoint (US doesn't ask).
        self.posthog_code_integration.delete()
        Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-notifications"},
        )
        mock_proxy.return_value = "proxied"
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")

        from products.slack_app.backend.api import ROUTE_PROXIED, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345")

        assert result == ROUTE_PROXIED
        mock_proxy.assert_called_once()
        # Target is the EU domain — never the incoming host.
        assert mock_proxy.call_args.args[1] == "eu.posthog.com"
        mock_sync_connect.assert_not_called()
        mock_asyncio_run.assert_not_called()

    @patch("products.slack_app.backend.api._proxy_event_and_return_route")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_loop_header_with_only_notifications_returns_no_integration(
        self, mock_sync_connect, mock_asyncio_run, mock_proxy
    ):
        # The second hop must not bounce the event back. Without local coding-agent install AND
        # the loop header set, we drop with ROUTE_NO_INTEGRATION rather than proxy again.
        self.posthog_code_integration.delete()
        Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-notifications"},
        )
        request = self.factory.post(
            "/slack/event-callback/",
            HTTP_HOST="us.posthog.com",
            headers={"x-posthog-region-proxied": "1"},
        )

        from products.slack_app.backend.api import ROUTE_NO_INTEGRATION, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345")

        assert result == ROUTE_NO_INTEGRATION
        mock_proxy.assert_not_called()
        mock_sync_connect.assert_not_called()
        mock_asyncio_run.assert_not_called()

    @patch("products.slack_app.backend.api._proxy_event_and_return_route")
    @override_settings(DEBUG=False)
    def test_us_no_local_proxies_to_eu(self, mock_proxy):
        mock_proxy.return_value = "proxied"
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")

        from products.slack_app.backend.api import ROUTE_PROXIED, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T_UNKNOWN")

        assert result == ROUTE_PROXIED
        mock_proxy.assert_called_once()
        assert mock_proxy.call_args.args[1] == "eu.posthog.com"

    @patch("products.slack_app.backend.api._proxy_event_and_return_route")
    @override_settings(DEBUG=False)
    def test_proxy_failure_returns_proxy_failed(self, mock_proxy):
        mock_proxy.return_value = "proxy_failed"
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")

        from products.slack_app.backend.api import ROUTE_PROXY_FAILED, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T_UNKNOWN")

        assert result == ROUTE_PROXY_FAILED

    @patch("products.slack_app.backend.api._proxy_event_and_return_route")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_no_local_with_loop_header_returns_no_integration(self, mock_sync_connect, mock_asyncio_run, mock_proxy):
        request = self.factory.post(
            "/slack/event-callback/",
            HTTP_HOST="us.posthog.com",
            headers={"x-posthog-region-proxied": "1"},
        )

        from products.slack_app.backend.api import ROUTE_NO_INTEGRATION, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T_UNKNOWN")

        assert result == ROUTE_NO_INTEGRATION
        mock_sync_connect.assert_not_called()
        mock_asyncio_run.assert_not_called()
        mock_proxy.assert_not_called()

    @patch("products.slack_app.backend.api.does_other_region_claim_workspace")
    @patch("products.slack_app.backend.api._proxy_event_and_return_route")
    @patch("products.slack_app.backend.api._posthog_code_enabled_for_integration", return_value=True)
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_eu_local_match_with_us_lookup_true_proxies_to_us(
        self, mock_sync_connect, mock_asyncio_run, _mock_flag, mock_proxy, mock_lookup
    ):
        # EU has the coding-agent install AND US confirms it has the same workspace.
        # US-precedence: EU must defer rather than handle locally.
        mock_lookup.return_value = True
        mock_proxy.return_value = "proxied"
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="eu.posthog.com")

        from products.slack_app.backend.api import ROUTE_PROXIED, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345")

        assert result == ROUTE_PROXIED
        mock_lookup.assert_called_once()
        assert mock_lookup.call_args.kwargs["kinds"] == ["slack-posthog-code"]
        mock_proxy.assert_called_once()
        assert mock_proxy.call_args.args[1] == "us.posthog.com"
        mock_sync_connect.assert_not_called()
        mock_asyncio_run.assert_not_called()

    @patch("products.slack_app.backend.api.does_other_region_claim_workspace")
    @patch("products.slack_app.backend.api._posthog_code_enabled_for_integration", return_value=True)
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_eu_local_match_with_us_lookup_false_handles_locally(
        self, mock_sync_connect, mock_asyncio_run, _mock_flag, mock_lookup
    ):
        mock_lookup.return_value = False
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="eu.posthog.com")

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_lookup.assert_called_once()
        mock_sync_connect.assert_called_once()
        mock_sync_connect.return_value.start_workflow.assert_called_once()

    @patch("products.slack_app.backend.api.does_other_region_claim_workspace")
    @patch("products.slack_app.backend.api._posthog_code_enabled_for_integration", return_value=True)
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_eu_local_match_with_us_lookup_failure_falls_back_to_local(
        self, mock_sync_connect, mock_asyncio_run, _mock_flag, mock_lookup
    ):
        # Lookup returns None on transport failure / bad response. Falling back to local handling
        # is safer than dropping — at worst we double-handle if US later turns out to own this.
        mock_lookup.return_value = None
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="eu.posthog.com")

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_lookup.assert_called_once()
        mock_sync_connect.assert_called_once()

    @patch("products.slack_app.backend.api.does_other_region_claim_workspace")
    @patch("products.slack_app.backend.api._proxy_event_and_return_route")
    @override_settings(DEBUG=False)
    def test_eu_no_local_proxies_to_us_without_lookup(self, mock_proxy, mock_lookup):
        mock_proxy.return_value = "proxied"
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="eu.posthog.com")

        from products.slack_app.backend.api import ROUTE_PROXIED, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T_UNKNOWN")

        assert result == ROUTE_PROXIED
        # No need to ask "do you have it" when we know we don't and just have to defer.
        mock_lookup.assert_not_called()
        mock_proxy.assert_called_once()
        assert mock_proxy.call_args.args[1] == "us.posthog.com"

    @patch("products.slack_app.backend.api.does_other_region_claim_workspace")
    @patch("products.slack_app.backend.api._posthog_code_enabled_for_integration", return_value=True)
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_eu_local_match_with_loop_header_skips_lookup_and_handles(
        self, mock_sync_connect, mock_asyncio_run, _mock_flag, mock_lookup
    ):
        # If the other region forwarded the event to us we already know they couldn't handle it;
        # skipping the lookup avoids ping-pong and a wasted round trip.
        request = self.factory.post(
            "/slack/event-callback/",
            HTTP_HOST="eu.posthog.com",
            headers={"x-posthog-region-proxied": "1"},
        )

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_lookup.assert_not_called()
        mock_sync_connect.assert_called_once()

    @parameterized.expand(
        [
            # Pre-2026-05-04 prod installs only granted the 4 base scopes.
            ("four_base_scopes", "channels:read,groups:read,chat:write,chat:write.customize", False),
            # Fail-closed when the scope field is absent entirely.
            ("no_scope_field", None, False),
            # Follow-up mentions in an existing thread must also be gated.
            ("followup_with_partial_scopes", "channels:read,chat:write", True),
        ]
    )
    @patch("products.slack_app.backend.api._post_slack_user_feedback")
    @patch("products.slack_app.backend.api._posthog_code_enabled_for_integration", return_value=True)
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_app_mention_with_missing_scopes_posts_reauth_and_skips_workflow(
        self,
        _name,
        scope_value: str | None,
        seed_pending_picker: bool,
        mock_sync_connect,
        mock_asyncio_run,
        _mock_flag,
        mock_post_feedback,
    ):
        if scope_value is None:
            self.posthog_code_integration.config = {}
        else:
            self.posthog_code_integration.config["scope"] = scope_value
        self.posthog_code_integration.save(update_fields=["config"])

        from products.slack_app.backend.api import (
            ROUTE_HANDLED_LOCALLY,
            _set_pending_repo_picker,
            route_posthog_code_event_to_relevant_region,
        )

        if seed_pending_picker:
            _set_pending_repo_picker(
                integration_id=self.posthog_code_integration.id,
                channel="C001",
                thread_ts="1234.5678",
                slack_user_id="U123",
                workflow_id="posthog-code-mention-T12345:pending",
                context_token="ctx-1",
                message_ts="1234.7777",
            )

        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        event = {
            "type": "app_mention",
            "channel": "C001",
            "user": "U123",
            "ts": "1234.5678",
            "thread_ts": "1234.5678",
        }

        result = route_posthog_code_event_to_relevant_region(request, event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_sync_connect.assert_not_called()
        mock_sync_connect.return_value.get_workflow_handle.assert_not_called()
        mock_asyncio_run.assert_not_called()
        mock_post_feedback.assert_called_once()

        feedback_text = mock_post_feedback.call_args.args[4]
        assert "missing" in feedback_text.lower() and "reconnect" in feedback_text.lower()
        # The message enumerates scopes that are actually missing (e.g. app_mentions:read is
        # never in a pre-2026-05-04 install). Scopes the install already has must not appear.
        assert "app_mentions:read" in feedback_text
        if scope_value and "chat:write.customize" in scope_value:
            assert "chat:write.customize" not in feedback_text

    @patch("products.slack_app.backend.api._post_slack_user_feedback")
    @patch("ee.billing.quota_limiting.is_team_limited", return_value=True)
    @patch("products.slack_app.backend.api._posthog_code_enabled_for_integration", return_value=True)
    @patch("products.slack_app.backend.api.SlackIntegration")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False)
    def test_over_quota_team_still_starts_workflow_for_in_workflow_enforcement(
        self,
        mock_sync_connect,
        mock_asyncio_run,
        mock_slack_cls,
        _mock_flag,
        _mock_is_team_limited,
        mock_post_feedback,
    ):
        mock_slack_instance = mock_slack_cls.return_value
        mock_slack_instance.missing_scopes.return_value = set()

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        request = self.factory.post("/slack/event-callback/", HTTP_HOST="eu.posthog.com")
        event = {
            "type": "app_mention",
            "channel": "C001",
            "user": "U123",
            "ts": "1234.5678",
            "thread_ts": "1234.5678",
        }

        result = route_posthog_code_event_to_relevant_region(request, event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        # Quota enforcement now lives entirely inside the workflow — the webhook
        # always schedules it, and the activity-level gate posts the denial
        # before any billable LLM call. This guarantees a single owner for the
        # quota decision instead of dual gating.
        mock_sync_connect.assert_called_once()
        mock_asyncio_run.assert_called_once()
        mock_post_feedback.assert_not_called()
