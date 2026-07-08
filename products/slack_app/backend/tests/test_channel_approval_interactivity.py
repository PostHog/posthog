import json
import time
from typing import Any

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.api import (
    CHANNEL_APPROVAL_ACTION_APPROVE,
    CHANNEL_APPROVAL_ACTION_DENY,
    CHANNEL_APPROVAL_BLOCK_ID_PREFIX,
    CHANNEL_APPROVAL_CONTEXT_KIND,
    _picker_context_cache_key,
)
from products.slack_app.backend.models import SlackChannel
from products.slack_app.backend.tests.helpers import sign_slack_request


@override_settings(DEBUG=True)
class _ChannelApprovalTestBase(TestCase):
    # DEBUG=True keeps the interactivity handler local-only — without it, an
    # un-decodable / foreign-workspace payload triggers a real cross-region
    # proxy attempt and Django returns 502 in tests.

    signing_secret = "posthog-code-test-secret"
    slack_team_id = "T12345"
    slack_channel_id = "C_EXT"
    response_url = "https://hooks.slack.example/response/abc"

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

        self.context_token = "approval-token-123"
        self.thread_ts = "1700000000.000001"
        cache.set(
            _picker_context_cache_key(self.context_token),
            {
                "kind": CHANNEL_APPROVAL_CONTEXT_KIND,
                "integration_id": self.integration.id,
                "slack_workspace_id": self.slack_team_id,
                "slack_channel_id": self.slack_channel_id,
                "thread_ts": self.thread_ts,
                "created_at": int(time.time()),
            },
            timeout=900,
        )

    def _post_interactivity(self, payload: dict[str, Any]) -> Any:
        payload = {"team": {"id": self.slack_team_id}, **payload}
        body_str = f"payload={json.dumps(payload)}"
        body = body_str.encode()
        signature, ts = sign_slack_request(body, self.signing_secret)
        return self.client.post(
            "/slack/interactivity-callback/",
            data=body_str,
            content_type="application/x-www-form-urlencoded",
            headers={"x-slack-signature": signature, "x-slack-request-timestamp": ts},
        )

    def _approve_payload(self, slack_user_id: str) -> dict[str, Any]:
        return self._click_payload(slack_user_id, CHANNEL_APPROVAL_ACTION_APPROVE)

    def _deny_payload(self, slack_user_id: str) -> dict[str, Any]:
        return self._click_payload(slack_user_id, CHANNEL_APPROVAL_ACTION_DENY)

    def _click_payload(self, slack_user_id: str, action_id: str) -> dict[str, Any]:
        return {
            "type": "block_actions",
            "user": {"id": slack_user_id},
            "response_url": self.response_url,
            "actions": [
                {
                    "action_id": action_id,
                    "block_id": f"{CHANNEL_APPROVAL_BLOCK_ID_PREFIX}_actions:{self.context_token}",
                    "value": self.context_token,
                }
            ],
        }


@patch("products.slack_app.backend.api.requests.post")
@patch("products.slack_app.backend.api.SlackIntegration")
class TestChannelApprovalInteractivity(_ChannelApprovalTestBase):
    # We mock the whole ``SlackIntegration`` class so that:
    #   - ``SlackIntegration.slack_config()`` returns our test signing secret
    #     (needed to pass the Slack request validation at the endpoint).
    #   - ``SlackIntegration(integration).client.chat_postMessage`` is auto-mocked,
    #     so the approval handler's public threaded reply is assertable without
    #     hitting Slack.

    def _set_signing_secret(self, mock_slack_cls: Any) -> None:
        mock_slack_cls.slack_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}

    def _stub_slack_user_email(self, email: str) -> Any:
        return patch(
            "products.slack_app.backend.api.get_slack_user_info",
            return_value={"user": {"profile": {"email": email}}},
        )

    def _assert_ephemeral_deleted(self, mock_post: Any) -> None:
        # Every click outcome cleans up the ephemeral prompt via ``response_url``.
        mock_post.assert_called_once()
        assert mock_post.call_args.args[0] == self.response_url
        assert mock_post.call_args.kwargs["json"] == {"delete_original": True}

    def _assert_outcome_posted(self, mock_slack_cls: Any, fragment: str) -> None:
        # The channel-visible record is a public threaded ``chat_postMessage``.
        mock_chat = mock_slack_cls.return_value.client.chat_postMessage
        mock_chat.assert_called_once()
        assert mock_chat.call_args.kwargs["channel"] == self.slack_channel_id
        assert mock_chat.call_args.kwargs["thread_ts"] == self.thread_ts
        assert fragment in mock_chat.call_args.kwargs["text"]

    def test_approve_by_org_member_creates_row(self, mock_slack_cls, mock_post):
        self._set_signing_secret(mock_slack_cls)

        with self._stub_slack_user_email(self.member_user.email):
            response = self._post_interactivity(self._approve_payload("U_MEMBER"))

        assert response.status_code == 200
        row = SlackChannel.objects.get(slack_workspace_id=self.slack_team_id, slack_channel_id=self.slack_channel_id)
        assert row.approved_at is not None
        assert row.approved_by_id == self.member_user.id

        self._assert_outcome_posted(mock_slack_cls, "enabled the PostHog Slack app")
        self._assert_ephemeral_deleted(mock_post)
        # Context cache cleared so a forwarded click can't replay this approval.
        assert cache.get(_picker_context_cache_key(self.context_token)) is None

    def test_approve_by_non_member_does_not_create_row(self, mock_slack_cls, mock_post):
        self._set_signing_secret(mock_slack_cls)

        with self._stub_slack_user_email("outsider@example.com"):
            response = self._post_interactivity(self._approve_payload("U_OUTSIDER"))

        assert response.status_code == 200
        assert not SlackChannel.objects.filter(
            slack_workspace_id=self.slack_team_id, slack_channel_id=self.slack_channel_id
        ).exists()

        self._assert_outcome_posted(mock_slack_cls, "Only members of")
        self._assert_ephemeral_deleted(mock_post)
        # Token preserved: a legit org member could still mention the bot to get
        # a fresh prompt; we don't burn the token just because someone unauthorised clicked.
        assert cache.get(_picker_context_cache_key(self.context_token)) is not None

    def test_approve_with_no_resolvable_email_does_not_create_row(self, mock_slack_cls, mock_post):
        self._set_signing_secret(mock_slack_cls)

        with patch(
            "products.slack_app.backend.api.get_slack_user_info",
            return_value={"user": {"profile": {}}},
        ):
            response = self._post_interactivity(self._approve_payload("U_NO_EMAIL"))

        assert response.status_code == 200
        assert not SlackChannel.objects.filter(
            slack_workspace_id=self.slack_team_id, slack_channel_id=self.slack_channel_id
        ).exists()
        self._assert_outcome_posted(mock_slack_cls, "Only members of")
        self._assert_ephemeral_deleted(mock_post)

    def test_approve_with_foreign_workspace_is_silently_dropped(self, mock_slack_cls, mock_post):
        # The interactivity dispatcher's "is this local?" gate already refuses payloads
        # whose ``team.id`` doesn't match the context's integration's workspace, so a
        # forwarded/replayed click never reaches the approval handler at all.
        self._set_signing_secret(mock_slack_cls)

        with self._stub_slack_user_email(self.member_user.email):
            payload = self._approve_payload("U_MEMBER")
            payload["team"] = {"id": "T_OTHER_WORKSPACE"}
            response = self._post_interactivity(payload)

        assert response.status_code == 200
        assert not SlackChannel.objects.filter(
            slack_workspace_id=self.slack_team_id, slack_channel_id=self.slack_channel_id
        ).exists()
        mock_post.assert_not_called()
        mock_slack_cls.return_value.client.chat_postMessage.assert_not_called()

    def test_approve_with_expired_context_is_silently_dropped(self, mock_slack_cls, mock_post):
        self._set_signing_secret(mock_slack_cls)
        cache.delete(_picker_context_cache_key(self.context_token))

        with self._stub_slack_user_email(self.member_user.email):
            response = self._post_interactivity(self._approve_payload("U_MEMBER"))

        assert response.status_code == 200
        assert not SlackChannel.objects.filter(
            slack_workspace_id=self.slack_team_id, slack_channel_id=self.slack_channel_id
        ).exists()
        # The outer dispatcher drops payloads it can't tie to a local integration; the
        # approval handler is never reached, so neither outcome nor cleanup happens.
        mock_post.assert_not_called()
        mock_slack_cls.return_value.client.chat_postMessage.assert_not_called()

    def test_concurrent_approve_clicks_yield_single_row(self, mock_slack_cls, mock_post):
        self._set_signing_secret(mock_slack_cls)

        # Simulate the second click landing while the row already exists.
        SlackChannel.objects.create(
            slack_workspace_id=self.slack_team_id,
            slack_channel_id=self.slack_channel_id,
            approved_at=timezone.now(),
            approved_by=self.member_user,
        )
        # Re-seed the context (the first click would have cleared it).
        cache.set(
            _picker_context_cache_key(self.context_token),
            {
                "kind": "channel_approval",
                "integration_id": self.integration.id,
                "slack_workspace_id": self.slack_team_id,
                "slack_channel_id": self.slack_channel_id,
                "thread_ts": self.thread_ts,
                "created_at": int(time.time()),
            },
            timeout=900,
        )

        with self._stub_slack_user_email(self.member_user.email):
            response = self._post_interactivity(self._approve_payload("U_MEMBER"))

        assert response.status_code == 200
        # ``update_or_create`` preserves uniqueness; only one row ever.
        assert (
            SlackChannel.objects.filter(
                slack_workspace_id=self.slack_team_id, slack_channel_id=self.slack_channel_id
            ).count()
            == 1
        )
        self._assert_outcome_posted(mock_slack_cls, "enabled the PostHog Slack app")
        self._assert_ephemeral_deleted(mock_post)

    def test_deny_by_org_member_posts_dismissal(self, mock_slack_cls, mock_post):
        self._set_signing_secret(mock_slack_cls)

        with self._stub_slack_user_email(self.member_user.email):
            response = self._post_interactivity(self._deny_payload("U_MEMBER"))

        assert response.status_code == 200
        assert not SlackChannel.objects.filter(
            slack_workspace_id=self.slack_team_id, slack_channel_id=self.slack_channel_id
        ).exists()
        assert cache.get(_picker_context_cache_key(self.context_token)) is None
        self._assert_outcome_posted(mock_slack_cls, "dismissed the PostHog Slack app")
        self._assert_ephemeral_deleted(mock_post)

    def test_deny_by_non_member_posts_rejection(self, mock_slack_cls, mock_post):
        self._set_signing_secret(mock_slack_cls)

        with self._stub_slack_user_email("outsider@example.com"):
            response = self._post_interactivity(self._deny_payload("U_OUTSIDER"))

        assert response.status_code == 200
        self._assert_outcome_posted(mock_slack_cls, "Only members of")
        self._assert_ephemeral_deleted(mock_post)
        # Token preserved for any future legit member click.
        assert cache.get(_picker_context_cache_key(self.context_token)) is not None
