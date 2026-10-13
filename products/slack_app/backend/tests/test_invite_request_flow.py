import json
from typing import Any

from unittest.mock import MagicMock, PropertyMock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.test.client import RequestFactory
from django.utils import timezone

from rest_framework.test import APIClient

from posthog.models import Organization, OrganizationDomain, OrganizationInvite, OrganizationMembership, Team, User
from posthog.models.integration import Integration

from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, SLACK_MENTION_DROPPED_EVENT
from products.slack_app.backend.models import SlackUserProfileCache
from products.slack_app.backend.services import invite_request
from products.slack_app.backend.services.slack_auth import write_auth_state_ok
from products.slack_app.backend.services.slack_scopes import REQUIRED_SLACK_SCOPES
from products.slack_app.backend.tests.helpers import sign_slack_request

WORKSPACE = "T12345"
REQUESTER = "U_STRANGER"
REQUESTER_EMAIL = "stranger@example.com"
INSTALLER = "U_INSTALLER"
SIGNING_SECRET = "posthog-code-test-secret"
RESPONSE_URL = "https://hooks.slack.example/response/abc"


class TestInviteRequestFlow(TestCase):
    def setUp(self):
        cache.clear()
        self.enterContext(patch("products.slack_app.backend.api.does_other_region_claim_workspace", return_value=False))
        self.enterContext(
            patch(
                "products.slack_app.backend.api.SlackIntegration.slack_config",
                return_value={"SLACK_APP_SIGNING_SECRET": SIGNING_SECRET},
            )
        )
        self.slack_client = MagicMock()
        self.enterContext(
            patch(
                "products.slack_app.backend.api.SlackIntegration.client",
                new_callable=PropertyMock,
                return_value=self.slack_client,
            )
        )
        self.enterContext(patch("products.slack_app.backend.api.is_email_available", return_value=True))
        self.enterContext(
            patch("products.slack_app.backend.services.invite_request.is_email_available", return_value=True)
        )
        self.mock_send_invite = self.enterContext(
            patch("products.slack_app.backend.services.invite_request.send_invite.apply_async")
        )
        self.mock_response_url = self.enterContext(
            patch("products.slack_app.backend.services.inbox_interactivity.requests.post")
        )
        self.mock_reply = self.enterContext(
            patch("products.slack_app.backend.api._post_slack_user_feedback", return_value=True)
        )
        self.mock_capture = self.enterContext(patch("products.slack_app.backend.api.posthoganalytics.capture"))

        self.organization = Organization.objects.create(name="Acme")
        self.team = Team.objects.create(organization=self.organization, name="Production")
        self.installer = User.objects.create(email="ivy@example.com", distinct_id="u-installer", first_name="Ivy")
        self.membership = OrganizationMembership.objects.create(organization=self.organization, user=self.installer)
        self.integration = self._connect(self.team, created_by=self.installer)
        self.event = {
            "type": "app_mention",
            "channel": "C001",
            "user": REQUESTER,
            "ts": "1234.5678",
            "text": "<@U0BOT> how many signups last week",
        }

    def _connect(self, team: Team, *, created_by: User | None) -> Integration:
        integration = Integration.objects.create(
            team=team,
            kind="slack",
            integration_id=WORKSPACE,
            config={"scope": ",".join(sorted(REQUIRED_SLACK_SCOPES)), "authed_user": {"id": INSTALLER}},
            sensitive_config={"access_token": "xoxb-test"},
            created_by=created_by,
        )
        write_auth_state_ok(integration.id, bot_user_id="U0BOT")
        SlackUserProfileCache.objects.create(
            integration=integration,
            slack_user_id=REQUESTER,
            email=REQUESTER_EMAIL,
            display_name="Stranger",
            real_name="A Stranger",
            refreshed_at=timezone.now(),
        )
        return integration

    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def _mention(self) -> str:
        from products.slack_app.backend.api import route_posthog_code_event_to_relevant_region

        request = RequestFactory().post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        result = route_posthog_code_event_to_relevant_region(request, self.event, WORKSPACE, "Ev001")
        assert result == ROUTE_HANDLED_LOCALLY
        return self.mock_reply.call_args.args[4]

    def _dm_blocks(self) -> list[dict[str, Any]]:
        return self.slack_client.chat_postMessage.call_args.kwargs["blocks"]

    @override_settings(DEBUG=True)
    def _click(self, blocks: list[dict], *, action_id: str, slack_user_id: str = INSTALLER) -> None:
        actions_block = next(block for block in blocks if block["type"] == "actions")
        element = next(element for element in actions_block["elements"] if element["action_id"] == action_id)
        payload = {
            "type": "block_actions",
            "team": {"id": WORKSPACE},
            "user": {"id": slack_user_id},
            "response_url": RESPONSE_URL,
            "actions": [{"action_id": action_id, "block_id": actions_block["block_id"], "value": element["value"]}],
        }
        body = f"payload={json.dumps(payload)}"
        signed = sign_slack_request(body.encode(), SIGNING_SECRET)
        response = APIClient().post(
            "/slack/interactivity-callback/",
            data=body,
            content_type="application/x-www-form-urlencoded",
            headers={"x-slack-signature": signed.signature, "x-slack-request-timestamp": signed.timestamp},
        )
        assert response.status_code == 200

    def _dm_replaced_with(self) -> str:
        return self.mock_response_url.call_args.kwargs["json"]["text"]

    def test_unmatched_mention_asks_the_installer_and_tells_the_requester(self):
        reply = self._mention()

        self.slack_client.chat_postMessage.assert_called_once()
        assert self.slack_client.chat_postMessage.call_args.kwargs["channel"] == INSTALLER
        assert REQUESTER_EMAIL in self._dm_blocks()[0]["text"]["text"]
        assert "I've asked Ivy to invite you" in reply
        drops = [
            c.kwargs["properties"]
            for c in self.mock_capture.call_args_list
            if c.kwargs["event"] == SLACK_MENTION_DROPPED_EVENT
        ]
        assert drops[0]["invite_requested"] is True

    def test_approval_sends_a_member_invite_from_the_approver(self):
        self._mention()

        self._click(self._dm_blocks(), action_id=invite_request.INVITE_REQUEST_ACTION_APPROVE)

        invite = OrganizationInvite.objects.get(organization=self.organization)
        assert (invite.target_email, invite.created_by_id, invite.level) == (
            REQUESTER_EMAIL,
            self.installer.id,
            OrganizationMembership.Level.MEMBER,
        )
        self.mock_send_invite.assert_called_once_with(kwargs={"invite_id": str(invite.id)})
        assert self._dm_replaced_with() == f"Invite sent to {REQUESTER_EMAIL}."

    def test_decline_sends_nothing(self):
        self._mention()

        self._click(self._dm_blocks(), action_id=invite_request.INVITE_REQUEST_ACTION_DECLINE)

        assert OrganizationInvite.objects.count() == 0
        assert self._dm_replaced_with() == invite_request.REQUEST_DECLINED_MESSAGE

    def test_click_from_anyone_but_the_approver_sends_nothing(self):
        self._mention()

        self._click(self._dm_blocks(), action_id=invite_request.INVITE_REQUEST_ACTION_APPROVE, slack_user_id="U_OTHER")

        assert OrganizationInvite.objects.count() == 0
        self.mock_response_url.assert_not_called()

    def test_approver_who_lost_permission_sends_nothing(self):
        self._mention()
        self.membership.delete()

        self._click(self._dm_blocks(), action_id=invite_request.INVITE_REQUEST_ACTION_APPROVE)

        assert OrganizationInvite.objects.count() == 0
        assert self._dm_replaced_with() == invite_request.APPROVER_LOST_PERMISSION_MESSAGE

    def test_click_after_the_request_expired_tells_the_approver(self):
        self._mention()
        cache.clear()

        self._click(self._dm_blocks(), action_id=invite_request.INVITE_REQUEST_ACTION_APPROVE)

        assert OrganizationInvite.objects.count() == 0
        assert self._dm_replaced_with() == invite_request.REQUEST_EXPIRED_MESSAGE

    def test_second_mention_on_the_same_day_sends_one_request(self):
        self._mention()
        reply = self._mention()

        self.slack_client.chat_postMessage.assert_called_once()
        assert "I've already asked Ivy to invite you today" in reply

    def test_verified_domain_with_automatic_joining_points_to_sign_in(self):
        OrganizationDomain.objects.create(
            organization=self.organization,
            domain="example.com",
            verified_at=timezone.now(),
            jit_provisioning_enabled=True,
        )

        reply = self._mention()

        self.slack_client.chat_postMessage.assert_not_called()
        assert "/login" in reply and REQUESTER_EMAIL in reply

    def test_workspace_connected_to_two_organizations_keeps_todays_reply(self):
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="t")
        self._connect(other_team, created_by=None)

        reply = self._mention()

        self.slack_client.chat_postMessage.assert_not_called()
        assert "ask an admin to invite" in reply
