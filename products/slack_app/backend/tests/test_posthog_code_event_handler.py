import json
from typing import Any

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.test.client import RequestFactory

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackUserProfileCache
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

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_url_verification(self, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        response = self._post_event({"type": "url_verification", "challenge": "test-challenge-123"})
        assert response.status_code == 200
        assert response.json() == {"challenge": "test-challenge-123"}

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_invalid_signature(self, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": "different-secret"}
        response = self._post_event({"type": "url_verification", "challenge": "test"})
        assert response.status_code == 403

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_retry_returns_200(self, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
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
            ("member_joined_channel_routes", "member_joined_channel", "handled_locally", 202, True),
            ("message_dm_routes", "message", "handled_locally", 202, True),
            ("non_handled_event_type_skips_routing", "reaction_added", "handled_locally", 202, False),
        ]
    )
    @patch("products.slack_app.backend.api.route_posthog_code_event_to_relevant_region")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
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
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
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
        from posthog.helpers.slack_scopes import REQUIRED_SLACK_SCOPES

        cache.clear()
        self.factory = RequestFactory()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-1")
        OrganizationMembership.objects.create(organization=self.organization, user=self.user)
        self.user.current_organization = self.organization
        self.user.current_team = self.team
        self.user.save()
        self.posthog_code_integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            config={"scope": ",".join(sorted(REQUIRED_SLACK_SCOPES))},
            sensitive_config={"access_token": "xoxb-posthog-code-test"},
        )
        # Seed the Slack-user → email cache so routing can resolve U123 → self.user
        # without calling the Slack API. New tests that exercise the unauthorised
        # paths override this row (or delete it) deliberately.
        self._seed_slack_user_cache("U123", "dev@example.com")
        self.event = {"type": "app_mention", "channel": "C001", "user": "U123", "ts": "1234.5678"}

    def _seed_slack_user_cache(self, slack_user_id: str, email: str | None) -> SlackUserProfileCache:
        from django.utils import timezone

        return SlackUserProfileCache.objects.create(
            integration=self.posthog_code_integration,
            slack_user_id=slack_user_id,
            email=email,
            display_name="Dev",
            real_name="Dev User",
            refreshed_at=timezone.now(),
        )

    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_local_match_starts_temporal_workflow(self, mock_sync_connect, mock_asyncio_run):
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
    @patch("products.slack_app.backend.api.SlackIntegration")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
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
                user_id=self.user.id,
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
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_app_mention_ignored_does_not_start_workflow(
        self,
        _name,
        ignore_marker: dict,
        mock_sync_connect,
        mock_asyncio_run,
    ):
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        ignored_event = {**self.event, **ignore_marker}

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, ignored_event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_sync_connect.assert_not_called()
        mock_asyncio_run.assert_not_called()

    @patch("products.slack_app.backend.api.posthoganalytics.capture")
    @patch("products.slack_app.backend.api._post_slack_user_feedback")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_app_mention_from_unknown_user_posts_in_thread_failure_reply(
        self, mock_sync_connect, mock_asyncio_run, mock_post_feedback, mock_capture
    ):
        # A Slack user whose email doesn't map to any PostHog ``User`` in any connected
        # org gets a public in-thread "Sorry, I couldn't find <email>…" reply that names
        # the looked-up Slack email so they can self-correct. The mention is still
        # captured to product analytics so the unknown-user funnel keeps its coverage.
        # No workflow starts.
        SlackUserProfileCache.objects.filter(slack_user_id="U123").delete()
        self._seed_slack_user_cache("U123", "stranger@example.com")

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_sync_connect.assert_not_called()
        mock_asyncio_run.assert_not_called()

        # Failure reply is posted in-thread and names the looked-up Slack email so the
        # user can spot a wrong-email mismatch against their PostHog account.
        mock_post_feedback.assert_called_once()
        feedback_text = mock_post_feedback.call_args.args[4]
        assert "stranger@example.com" in feedback_text
        assert mock_post_feedback.call_args.kwargs.get("prefer_thread_message") is True

        # The mention is still reported to analytics with ``posthog_user_identified=False``
        # so the unknown-user volume stays comparable to the known-user funnel.
        mock_capture.assert_called_once()
        capture_kwargs = mock_capture.call_args.kwargs
        assert capture_kwargs.get("event") == "posthog code slack mention received"
        assert capture_kwargs.get("properties", {}).get("posthog_user_identified") is False

    @patch("products.slack_app.backend.api.posthoganalytics.capture")
    @patch("products.slack_app.backend.api._post_slack_user_feedback")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_unknown_user_in_unapproved_ext_shared_channel_suppresses_failure_reply(
        self, mock_sync_connect, mock_asyncio_run, mock_post_feedback, mock_capture
    ):
        # Externally-shared channels that haven't been approved must not receive a
        # public "Sorry, I couldn't find <email>" post — that leaks the integration's
        # existence (and the user's email) to non-org members. The approval prompt
        # itself requires a resolved user, so we stay completely silent in this case.
        # Analytics still records the event for funnel coverage.
        SlackUserProfileCache.objects.filter(slack_user_id="U123").delete()
        self._seed_slack_user_cache("U123", "stranger@example.com")

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345", is_ext_shared_channel=True)

        assert result == ROUTE_HANDLED_LOCALLY
        mock_sync_connect.assert_not_called()
        mock_asyncio_run.assert_not_called()
        mock_post_feedback.assert_not_called()
        mock_capture.assert_called_once()

    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_app_mention_filters_candidates_to_user_accessible_only(self, mock_sync_connect, mock_asyncio_run):
        # When the workspace spans two orgs and the resolved PostHog user only
        # belongs to one of them, ``resolve_from_candidates`` filters the other
        # out so the workflow runs against the accessible integration.
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_integration = Integration.objects.create(
            team=other_team,
            kind="slack",
            integration_id="T12345",
            config=self.posthog_code_integration.config,
            sensitive_config={"access_token": "xoxb-other"},
        )

        from products.slack_app.backend.api import route_posthog_code_event_to_relevant_region

        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        route_posthog_code_event_to_relevant_region(request, self.event, "T12345")

        mock_sync_connect.return_value.start_workflow.assert_called_once()
        workflow_inputs = mock_sync_connect.return_value.start_workflow.call_args.args[1]
        # The user belongs to ``self.organization`` only, so only that integration
        # should be the mention target — ``other_integration`` is filtered out.
        assert workflow_inputs.integration_id == self.posthog_code_integration.id
        assert workflow_inputs.integration_id != other_integration.id

    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_app_mention_excludes_private_team_when_user_lacks_access_control_grant(
        self, mock_sync_connect, mock_asyncio_run
    ):
        # Regression: ``user.teams`` reads its access-control flag from a single
        # ``Organization.first()`` row, so a Slack user spanning an
        # ACCESS_CONTROL-enabled org and a non-AC org can otherwise appear to
        # have access to a private project they were never granted. The
        # per-team ``effective_membership_level`` check must drop that
        # integration before the workflow starts.
        from posthog.constants import AvailableFeature

        from ee.models.rbac.access_control import AccessControl

        ac_org = Organization.objects.create(name="AC Org")
        # The ``pre_save`` signal on ``Organization`` resets
        # ``available_product_features`` to ``[]`` on insert, so set it after the
        # initial save to opt the org into per-team access-control checks.
        ac_org.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        ac_org.save()
        private_team = Team.objects.create(organization=ac_org, name="Private Team")
        AccessControl.objects.create(
            team=private_team,
            resource="project",
            resource_id=str(private_team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )
        OrganizationMembership.objects.create(organization=ac_org, user=self.user)
        private_integration = Integration.objects.create(
            team=private_team,
            kind="slack",
            integration_id="T12345",
            config=self.posthog_code_integration.config,
            sensitive_config={"access_token": "xoxb-private"},
        )

        from products.slack_app.backend.api import route_posthog_code_event_to_relevant_region

        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        route_posthog_code_event_to_relevant_region(request, self.event, "T12345")

        mock_sync_connect.return_value.start_workflow.assert_called_once()
        workflow_inputs = mock_sync_connect.return_value.start_workflow.call_args.args[1]
        assert workflow_inputs.integration_id == self.posthog_code_integration.id
        assert workflow_inputs.integration_id != private_integration.id

    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_app_mention_passes_resolved_user_id_into_workflow_inputs(self, mock_sync_connect, mock_asyncio_run):
        # The routing layer must propagate the resolved PostHog user id into the
        # mention workflow inputs so the workflow can skip its legacy in-workflow
        # resolve activity.
        from products.slack_app.backend.api import route_posthog_code_event_to_relevant_region

        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        route_posthog_code_event_to_relevant_region(request, self.event, "T12345")

        mock_sync_connect.return_value.start_workflow.assert_called_once()
        workflow_inputs = mock_sync_connect.return_value.start_workflow.call_args.args[1]
        assert workflow_inputs.user_id == self.user.id

    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_command_workflow_receives_resolved_user_id(self, mock_sync_connect, mock_asyncio_run):
        # Command path mirrors the mention path: routing resolves the user once
        # and the command workflow gets ``user_id`` so it skips its legacy
        # resolve-user activity on replay-safe code paths.
        from products.slack_app.backend.api import route_posthog_code_event_to_relevant_region

        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        event = {**self.event, "text": "<@UBOT123> project 2"}

        route_posthog_code_event_to_relevant_region(request, event, "T12345")

        mock_sync_connect.return_value.start_workflow.assert_called_once()
        workflow_inputs = mock_sync_connect.return_value.start_workflow.call_args.args[1]
        assert workflow_inputs.user_id == self.user.id

    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_command_text_routes_to_command_workflow(self, mock_sync_connect, mock_asyncio_run):
        # Command text in a mention must dispatch the command workflow, never the agent
        # mention workflow — even when a single coding-agent integration exists.
        from posthog.temporal.ai.slack_app.posthog_code_slack_mention_command import (
            PostHogCodeSlackMentionCommandWorkflow,
        )

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        event = {**self.event, "text": "<@UBOT123> project 2"}

        result = route_posthog_code_event_to_relevant_region(request, event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_sync_connect.return_value.start_workflow.assert_called_once()
        kicked_off = mock_sync_connect.return_value.start_workflow.call_args.args[0]
        assert kicked_off == PostHogCodeSlackMentionCommandWorkflow.run
        mock_asyncio_run.assert_called_once()

    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_command_workflow_receives_all_workspace_candidates(self, mock_sync_connect, mock_asyncio_run):
        # When multiple coding-agent integrations exist for the same workspace, all of
        # their IDs must be forwarded to the command workflow so it can handle project
        # commands without the caller having to pre-resolve a single target.
        from posthog.models.team.team import Team

        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_integration = Integration.objects.create(
            team=other_team,
            kind="slack",
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

    @patch("products.slack_app.backend.api.does_other_region_claim_workspace", return_value=False)
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_rules_add_without_repo_routes_to_command_workflow_for_picker(
        self, mock_sync_connect, mock_asyncio_run, _mock_us_claim
    ):
        # ``rules add "description"`` with no inline repo is still a command, so
        # the webhook hands it to the command workflow. The command workflow
        # itself drives the interactive repo picker (its own signal handlers and
        # wait_condition); the agent mention workflow is never involved.
        from posthog.temporal.ai.slack_app.posthog_code_slack_mention_command import (
            PostHogCodeSlackMentionCommandWorkflow,
        )

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        request = self.factory.post("/slack/event-callback/", HTTP_HOST="eu.posthog.com")
        event = {**self.event, "text": '<@UBOT123> rules add "investigate flaky tests"'}

        result = route_posthog_code_event_to_relevant_region(request, event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_sync_connect.return_value.start_workflow.assert_called_once()
        kicked_off = mock_sync_connect.return_value.start_workflow.call_args.args[0]
        assert kicked_off == PostHogCodeSlackMentionCommandWorkflow.run

    @patch("products.slack_app.backend.api.handle_posthog_link_unfurl")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
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
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
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
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_us_no_local_proxies_to_eu(self, mock_proxy):
        mock_proxy.return_value = "proxied"
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")

        from products.slack_app.backend.api import ROUTE_PROXIED, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T_UNKNOWN")

        assert result == ROUTE_PROXIED
        mock_proxy.assert_called_once()
        assert mock_proxy.call_args.args[1] == "eu.posthog.com"

    @patch("products.slack_app.backend.api._proxy_event_and_return_route")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_proxy_failure_returns_proxy_failed(self, mock_proxy):
        mock_proxy.return_value = "proxy_failed"
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")

        from products.slack_app.backend.api import ROUTE_PROXY_FAILED, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T_UNKNOWN")

        assert result == ROUTE_PROXY_FAILED

    @patch("products.slack_app.backend.api._proxy_event_and_return_route")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
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
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_eu_local_match_with_us_lookup_true_proxies_to_us(
        self, mock_sync_connect, mock_asyncio_run, mock_proxy, mock_lookup
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
        assert mock_lookup.call_args.kwargs["kinds"] == ["slack"]
        mock_proxy.assert_called_once()
        assert mock_proxy.call_args.args[1] == "us.posthog.com"
        mock_sync_connect.assert_not_called()
        mock_asyncio_run.assert_not_called()

    @patch("products.slack_app.backend.api.does_other_region_claim_workspace")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_eu_local_match_with_us_lookup_false_handles_locally(
        self, mock_sync_connect, mock_asyncio_run, mock_lookup
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
    @patch("products.slack_app.backend.api._proxy_event_and_return_route")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_eu_local_match_with_us_lookup_failure_optimistically_proxies(
        self, mock_sync_connect, mock_asyncio_run, mock_proxy, mock_lookup
    ):
        # Lookup returns None on transport failure / bad response. We optimistically proxy to US
        # rather than handle locally: during cutover both regions hold a row, US is the rightful
        # owner, and one flake should not pin the event to EU. If US in fact has no row it sees
        # the proxied event with the loop header set and drops, which matches the prior outcome.
        mock_lookup.return_value = None
        mock_proxy.return_value = "proxied"
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="eu.posthog.com")

        from products.slack_app.backend.api import ROUTE_PROXIED, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345")

        assert result == ROUTE_PROXIED
        mock_lookup.assert_called_once()
        mock_proxy.assert_called_once()
        assert mock_proxy.call_args.args[1] == "us.posthog.com"
        mock_sync_connect.assert_not_called()

    @patch("products.slack_app.backend.api.does_other_region_claim_workspace")
    @patch("products.slack_app.backend.api._proxy_event_and_return_route")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
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
    @patch("products.slack_app.backend.api._proxy_event_and_return_route")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="DEV")
    def test_hosted_dev_does_not_cross_region_proxy(self, mock_sync_connect, mock_asyncio_run, mock_proxy, mock_lookup):
        # The hosted dev environment (app.dev.posthog.dev) runs as a single region and must not
        # probe or proxy to us.posthog.com — it has no row in that workspace and the upstream
        # responds 403 to every such hit (regression for slack_app_region_proxy_non_success).
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="app.dev.posthog.dev")

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345")

        assert result == ROUTE_HANDLED_LOCALLY
        mock_lookup.assert_not_called()
        mock_proxy.assert_not_called()
        mock_sync_connect.assert_called_once()

    @patch("products.slack_app.backend.api._proxy_event_and_return_route")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="DEV")
    def test_hosted_dev_no_local_match_drops_instead_of_proxying(self, mock_proxy):
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="app.dev.posthog.dev")

        from products.slack_app.backend.api import ROUTE_NO_INTEGRATION, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T_UNKNOWN")

        assert result == ROUTE_NO_INTEGRATION
        mock_proxy.assert_not_called()

    @patch("products.slack_app.backend.api.does_other_region_claim_workspace")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_eu_local_match_with_loop_header_skips_lookup_and_handles(
        self, mock_sync_connect, mock_asyncio_run, mock_lookup
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
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_app_mention_with_missing_scopes_posts_reauth_and_skips_workflow(
        self,
        _name,
        scope_value: str | None,
        seed_pending_picker: bool,
        mock_sync_connect,
        mock_asyncio_run,
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
                user_id=self.user.id,
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

    @patch("products.slack_app.backend.api.does_other_region_claim_workspace", return_value=False)
    @patch("products.slack_app.backend.api._post_slack_user_feedback")
    @patch("ee.billing.quota_limiting.is_team_limited", return_value=True)
    @patch("products.slack_app.backend.api.SlackIntegration")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_over_quota_team_still_starts_workflow_for_in_workflow_enforcement(
        self,
        mock_sync_connect,
        mock_asyncio_run,
        mock_slack_cls,
        _mock_is_team_limited,
        mock_post_feedback,
        _mock_us_claim,
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


class TestChannelApprovalGate(TestCase):
    """Gate covering the externally-shared-channel approval flow.

    The gate fires only when the Slack event envelope reports
    ``is_ext_shared_channel=True`` and no ``SlackChannel`` row with
    ``approved_at`` exists for ``(workspace, channel)``.
    """

    def setUp(self):
        from django.utils import timezone

        from posthog.helpers.slack_scopes import REQUIRED_SLACK_SCOPES

        cache.clear()
        self.factory = RequestFactory()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-1")
        OrganizationMembership.objects.create(organization=self.organization, user=self.user)
        self.user.current_organization = self.organization
        self.user.current_team = self.team
        self.user.save()
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            config={"scope": ",".join(sorted(REQUIRED_SLACK_SCOPES))},
            sensitive_config={"access_token": "xoxb-posthog-code-test"},
        )
        # Routing now resolves the Slack user to a PostHog user before any
        # channel-approval logic runs. Seed the cache so the gate has something
        # to resolve without calling Slack.
        SlackUserProfileCache.objects.create(
            integration=self.integration,
            slack_user_id="U123",
            email="dev@example.com",
            display_name="Dev",
            real_name="Dev User",
            refreshed_at=timezone.now(),
        )
        self.event = {
            "type": "app_mention",
            "channel": "C_EXT",
            "user": "U123",
            "ts": "1234.5678",
        }

    @patch("products.slack_app.backend.api._post_channel_approval_prompt")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_external_channel_without_approval_posts_prompt(self, mock_sync_connect, mock_asyncio_run, mock_prompt):
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345", is_ext_shared_channel=True)

        assert result == ROUTE_HANDLED_LOCALLY
        mock_prompt.assert_called_once()
        mock_sync_connect.assert_not_called()
        mock_asyncio_run.assert_not_called()

    @patch("products.slack_app.backend.api._post_channel_approval_prompt")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_external_channel_with_approval_starts_workflow(self, mock_sync_connect, mock_asyncio_run, mock_prompt):
        from django.utils import timezone

        from products.slack_app.backend.models import SlackChannel

        SlackChannel.objects.create(
            slack_workspace_id="T12345",
            slack_channel_id="C_EXT",
            approved_at=timezone.now(),
            approved_by=self.user,
        )
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345", is_ext_shared_channel=True)

        assert result == ROUTE_HANDLED_LOCALLY
        mock_prompt.assert_not_called()
        mock_sync_connect.assert_called_once()
        mock_sync_connect.return_value.start_workflow.assert_called_once()
        mock_asyncio_run.assert_called_once()

    @patch("products.slack_app.backend.api._post_channel_approval_prompt")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_non_external_channel_starts_workflow_without_prompt(
        self, mock_sync_connect, mock_asyncio_run, mock_prompt
    ):
        # ``is_ext_shared_channel=False`` mirrors the envelope flag being absent /
        # false; the gate doesn't fire and the workflow starts normally.
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345", is_ext_shared_channel=False)

        assert result == ROUTE_HANDLED_LOCALLY
        mock_prompt.assert_not_called()
        mock_sync_connect.return_value.start_workflow.assert_called_once()
        mock_asyncio_run.assert_called_once()

    @patch("products.slack_app.backend.api._post_channel_approval_prompt")
    @patch("products.slack_app.backend.api.asyncio.run")
    @patch("products.slack_app.backend.api.sync_connect")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_pending_row_without_approval_still_prompts(self, mock_sync_connect, mock_asyncio_run, mock_prompt):
        # A row with ``approved_at`` NULL has no semantic weight today, but must not bypass the
        # gate — only ``approved_at`` being set counts as approval.
        from products.slack_app.backend.models import SlackChannel

        SlackChannel.objects.create(
            slack_workspace_id="T12345",
            slack_channel_id="C_EXT",
            approved_at=None,
        )
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")

        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        result = route_posthog_code_event_to_relevant_region(request, self.event, "T12345", is_ext_shared_channel=True)

        assert result == ROUTE_HANDLED_LOCALLY
        mock_prompt.assert_called_once()
        mock_sync_connect.assert_not_called()
        mock_asyncio_run.assert_not_called()

    @patch("products.slack_app.backend.api.route_posthog_code_event_to_relevant_region")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_envelope_ext_shared_flag_is_forwarded_to_router(self, mock_config, mock_route):
        # End-to-end through the HTTP endpoint: the envelope's ``is_ext_shared_channel``
        # must flow into the routing function — otherwise the gate would silently never
        # fire on real Slack traffic.
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": "secret"}
        mock_route.return_value = "handled_locally"

        envelope = {
            "type": "event_callback",
            "team_id": "T12345",
            "is_ext_shared_channel": True,
            "event": {"type": "app_mention", "channel": "C_EXT", "user": "U123", "ts": "1.0"},
        }
        body = json.dumps(envelope).encode()
        signature, ts = sign_slack_request(body, "secret")
        APIClient().post(
            "/slack/event-callback/",
            data=body,
            content_type="application/json",
            HTTP_X_SLACK_SIGNATURE=signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
        )

        mock_route.assert_called_once()
        assert mock_route.call_args.kwargs["is_ext_shared_channel"] is True


class TestAssistantEvents(TestCase):
    def setUp(self):
        from posthog.helpers.slack_scopes import REQUIRED_SLACK_SCOPES

        cache.clear()
        self.factory = RequestFactory()
        self.organization = Organization.objects.create(name="Assistant Org")
        self.team = Team.objects.create(organization=self.organization, name="Assistant Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="assistant-user-1")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            config={"scope": ",".join(sorted(REQUIRED_SLACK_SCOPES))},
            sensitive_config={"access_token": "xoxb-test"},
        )

    def _route(self, event: dict):
        from products.slack_app.backend.api import route_posthog_code_event_to_relevant_region

        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        with override_settings(DEBUG=False):
            return route_posthog_code_event_to_relevant_region(request, event, "T12345")

    def _patch_resolution(self, *, user, enabled=True):
        from products.slack_app.backend.services.integration_resolver import (
            ResolutionResult,
            UserAndIntegrationsResolution,
        )

        load = patch(
            "products.slack_app.backend.api.load_integrations",
            return_value=ResolutionResult(
                integration=self.integration, source="sole_candidate", candidates=[self.integration]
            ),
        )
        resolution = (
            UserAndIntegrationsResolution(
                user=user, integration=self.integration, candidates=[self.integration], source="sole_candidate"
            )
            if user is not None
            else UserAndIntegrationsResolution(failure_reason="user_not_found")
        )
        resolve = patch("products.slack_app.backend.api.resolve_user_for_workspace", return_value=resolution)
        enabled_p = patch("products.slack_app.backend.api._assistant_enabled", return_value=enabled)
        usp = patch("products.slack_app.backend.api._us_should_handle_instead", return_value=False)
        slack = patch("products.slack_app.backend.api.SlackIntegration")
        return load, resolve, enabled_p, usp, slack

    def test_assistant_thread_started_sets_prompts_for_member(self):
        load, resolve, enabled_p, usp, slack = self._patch_resolution(user=self.user)
        with load, resolve, enabled_p, usp, slack as slack_cls:
            slack_cls.return_value.missing_scopes.return_value = set()
            self._route(
                {
                    "type": "assistant_thread_started",
                    "assistant_thread": {"user_id": "U123", "channel_id": "D001", "thread_ts": "111.222"},
                }
            )
            slack_cls.return_value.client.assistant_threads_setSuggestedPrompts.assert_called_once()

    def test_assistant_thread_started_noop_for_non_member(self):
        load, resolve, enabled_p, usp, slack = self._patch_resolution(user=None)
        with load, resolve, enabled_p, usp, slack as slack_cls:
            self._route(
                {
                    "type": "assistant_thread_started",
                    "assistant_thread": {"user_id": "U123", "channel_id": "D001", "thread_ts": "111.222"},
                }
            )
            slack_cls.return_value.client.assistant_threads_setSuggestedPrompts.assert_not_called()

    def test_context_changed_caches_viewed_channel(self):
        from products.slack_app.backend.api import _get_assistant_channel_context

        load, resolve, enabled_p, usp, slack = self._patch_resolution(user=self.user)
        with load, resolve, enabled_p, usp, slack:
            self._route(
                {
                    "type": "assistant_thread_context_changed",
                    "assistant_thread": {
                        "user_id": "U123",
                        "channel_id": "D001",
                        "thread_ts": "111.222",
                        "context": {"channel_id": "C999"},
                    },
                }
            )
        assert _get_assistant_channel_context(self.integration.id, "D001", "111.222") == "C999"

    def test_dm_message_starts_agent(self):
        load, resolve, enabled_p, usp, slack = self._patch_resolution(user=self.user)
        start = patch("products.slack_app.backend.api._start_mention_workflow", return_value="handled_locally")
        with load, resolve, enabled_p, usp, slack as slack_cls, start as mock_start:
            slack_cls.return_value.missing_scopes.return_value = set()
            self._route(
                {
                    "type": "message",
                    "channel_type": "im",
                    "channel": "D001",
                    "user": "U123",
                    "text": "fix the funnel bug",
                    "ts": "111.222",
                }
            )
            slack_cls.return_value.client.assistant_threads_setStatus.assert_called_once()
            mock_start.assert_called_once()

    def test_dm_message_ignores_bot_and_non_im(self):
        start = patch("products.slack_app.backend.api._start_mention_workflow", return_value="handled_locally")
        with start as mock_start:
            self._route(
                {"type": "message", "channel_type": "im", "bot_id": "B1", "channel": "D001", "text": "hi", "ts": "1"}
            )
            self._route(
                {"type": "message", "channel_type": "channel", "channel": "C1", "user": "U1", "text": "hi", "ts": "1"}
            )
            mock_start.assert_not_called()

    def test_dm_message_flag_off_is_dark(self):
        # Kill-switch: flag off -> no user resolution, no agent start, and no reply at all.
        load, resolve, enabled_p, usp, slack = self._patch_resolution(user=self.user, enabled=False)
        start = patch("products.slack_app.backend.api._start_mention_workflow", return_value="handled_locally")
        with load, resolve as mock_resolve, enabled_p, usp, slack as slack_cls, start as mock_start:
            self._route(
                {
                    "type": "message",
                    "channel_type": "im",
                    "channel": "D001",
                    "user": "U123",
                    "text": "fix it",
                    "ts": "1.2",
                }
            )
            mock_resolve.assert_not_called()
            mock_start.assert_not_called()
            slack_cls.return_value.client.chat_postMessage.assert_not_called()


class TestAssistantInstallWelcome(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Install Org")
        self.team = Team.objects.create(organization=self.organization, name="Install Team")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_INSTALL",
            config={"authed_user": {"id": "U_INSTALLER"}},
            sensitive_config={"access_token": "xoxb-test"},
        )

    def _run(self, *, enabled: bool):
        from products.slack_app.backend.api import _ASSISTANT_INSTALL_WELCOME, send_assistant_install_welcome

        enabled_p = patch("products.slack_app.backend.api._assistant_enabled", return_value=enabled)
        slack = patch("products.slack_app.backend.api.SlackIntegration")
        with enabled_p, slack as slack_cls:
            send_assistant_install_welcome(self.integration)
        return slack_cls, _ASSISTANT_INSTALL_WELCOME

    def test_dms_installer_when_enabled(self):
        slack_cls, welcome = self._run(enabled=True)
        slack_cls.return_value.client.chat_postMessage.assert_called_once_with(channel="U_INSTALLER", text=welcome)

    def test_silent_when_flag_off(self):
        slack_cls, _ = self._run(enabled=False)
        slack_cls.return_value.client.chat_postMessage.assert_not_called()

    def test_no_post_without_authed_user(self):
        self.integration.config = {}
        self.integration.save()
        slack_cls, _ = self._run(enabled=True)
        slack_cls.return_value.client.chat_postMessage.assert_not_called()

    def test_slack_error_is_swallowed(self):
        from products.slack_app.backend.api import send_assistant_install_welcome

        enabled_p = patch("products.slack_app.backend.api._assistant_enabled", return_value=True)
        slack = patch("products.slack_app.backend.api.SlackIntegration")
        with enabled_p, slack as slack_cls:
            slack_cls.return_value.client.chat_postMessage.side_effect = Exception("slack down")
            send_assistant_install_welcome(self.integration)  # must not raise
