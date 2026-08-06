import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration, SlackIntegration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.signals.backend.facade.api import (
    get_default_slack_notification_channel,
    set_default_slack_notification_channel,
)
from products.slack_app.backend import inbox_channel


class TestInboxChannel:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        cache.clear()
        self.organization = Organization.objects.create(name="Org")
        self.team = Team.objects.create(organization=self.organization, name="Team")
        self.user = User.objects.create(email="installer@example.com", first_name="Installer")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            config={"scope": "channels:manage,chat:write"},
            sensitive_config={"access_token": "xoxb-test"},
        )

    def _client(self, mock_webclient_class):
        client = MagicMock()
        # Default: empty membership so onboarding DMs render normally unless a test says otherwise.
        client.conversations_members.return_value = {"members": [], "response_metadata": {"next_cursor": ""}}
        mock_webclient_class.return_value = client
        return client

    @patch("posthog.models.integration.WebClient")
    def test_creates_channel_and_sets_team_default(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        client.conversations_list.return_value = {"channels": [], "response_metadata": {"next_cursor": ""}}
        client.conversations_create.return_value = {"channel": {"id": "C999"}}

        result = inbox_channel.ensure_inbox_channel(self.integration)

        assert result == ("C999", "#posthog-inbox")
        client.conversations_create.assert_called_once_with(name="posthog-inbox", is_private=False)
        assert get_default_slack_notification_channel(self.team.id) == "C999|#posthog-inbox"

    @patch("posthog.models.integration.WebClient")
    def test_reuses_configured_channel(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        set_default_slack_notification_channel(self.team.id, "C777|#posthog-inbox")
        client.conversations_info.return_value = {"channel": {"id": "C777"}}

        result = inbox_channel.ensure_inbox_channel(self.integration)

        assert result == ("C777", "#posthog-inbox")
        client.conversations_create.assert_not_called()
        client.conversations_list.assert_not_called()

    @patch("posthog.models.integration.WebClient")
    def test_reuses_existing_channel_by_name_without_manage_scope(self, mock_webclient_class):
        # Without channels:manage we can't create, so the only path is to find an existing channel by name.
        client = self._client(mock_webclient_class)
        self.integration.config = {"scope": "chat:write"}
        self.integration.save()
        client.conversations_list.return_value = {
            "channels": [{"id": "C555", "name": "posthog-inbox"}],
            "response_metadata": {"next_cursor": ""},
        }

        result = inbox_channel.ensure_inbox_channel(self.integration)

        assert result == ("C555", "#posthog-inbox")
        client.conversations_create.assert_not_called()
        assert get_default_slack_notification_channel(self.team.id) == "C555|#posthog-inbox"

    @patch("posthog.models.integration.WebClient")
    def test_create_name_taken_falls_back_to_lookup(self, mock_webclient_class):
        # Create-first: we attempt to create straight away; name_taken triggers the lookup to resolve the id.
        client = self._client(mock_webclient_class)
        client.conversations_list.return_value = {
            "channels": [{"id": "C111", "name": "posthog-inbox"}],
            "response_metadata": {"next_cursor": ""},
        }
        client.conversations_create.side_effect = SlackApiError("name_taken", {"error": "name_taken"})

        result = inbox_channel.ensure_inbox_channel(self.integration)

        assert result == ("C111", "#posthog-inbox")
        assert get_default_slack_notification_channel(self.team.id) == "C111|#posthog-inbox"

    @patch("posthog.models.integration.WebClient")
    def test_missing_scope_and_no_channel_returns_none(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        self.integration.config = {"scope": "chat:write"}
        self.integration.save()
        client.conversations_list.return_value = {"channels": [], "response_metadata": {"next_cursor": ""}}

        result = inbox_channel.ensure_inbox_channel(self.integration)

        assert result is None
        client.conversations_create.assert_not_called()
        assert get_default_slack_notification_channel(self.team.id) is None

    @patch("posthog.models.integration.WebClient")
    def test_has_inbox_scopes(self, mock_webclient_class):
        self._client(mock_webclient_class)

        self.integration.config = {"scope": "channels:manage,chat:write"}
        self.integration.save()
        assert inbox_channel.has_inbox_scopes(self.integration) is True

        self.integration.config = {"scope": "chat:write"}
        self.integration.save()
        assert inbox_channel.has_inbox_scopes(self.integration) is False

    @patch("posthog.models.integration.WebClient")
    def test_is_inbox_channel_by_configured_id(self, mock_webclient_class):
        self._client(mock_webclient_class)
        set_default_slack_notification_channel(self.team.id, "C222|#posthog-inbox")

        assert inbox_channel.is_inbox_channel(self.integration, "C222") is True

    @patch("posthog.models.integration.WebClient")
    def test_is_inbox_channel_by_name_fallback(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        client.conversations_info.return_value = {"channel": {"id": "C333", "name": "posthog-inbox"}}

        assert inbox_channel.is_inbox_channel(self.integration, "C333") is True

    @patch("posthog.models.integration.WebClient")
    def test_is_inbox_channel_false_for_other_channel(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        client.conversations_info.return_value = {"channel": {"id": "C444", "name": "random"}}

        assert inbox_channel.is_inbox_channel(self.integration, "C444") is False

    @patch("posthog.models.integration.WebClient")
    def test_invite_success(self, mock_webclient_class):
        client = self._client(mock_webclient_class)

        assert inbox_channel.invite_user_to_inbox(self.integration, "C1", "U1") is True
        client.conversations_invite.assert_called_once_with(channel="C1", users="U1")

    @patch("posthog.models.integration.WebClient")
    def test_invite_already_in_channel_is_success(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        client.conversations_invite.side_effect = SlackApiError("already_in_channel", {"error": "already_in_channel"})

        assert inbox_channel.invite_user_to_inbox(self.integration, "C1", "U1") is True

    @patch("posthog.models.integration.WebClient")
    def test_invite_other_error_returns_false(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        client.conversations_invite.side_effect = SlackApiError("missing_scope", {"error": "missing_scope"})

        assert inbox_channel.invite_user_to_inbox(self.integration, "C1", "U1") is False

    @patch("posthog.models.integration.WebClient")
    def test_invite_joins_and_retries_on_not_in_channel(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        client.conversations_invite.side_effect = [
            SlackApiError("not_in_channel", {"error": "not_in_channel"}),
            {"ok": True},
        ]

        assert inbox_channel.invite_user_to_inbox(self.integration, "C1", "U1") is True
        client.conversations_join.assert_called_once_with(channel="C1")
        assert client.conversations_invite.call_count == 2

    @patch("posthog.models.integration.WebClient")
    def test_invite_returns_false_when_join_fails(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        client.conversations_invite.side_effect = SlackApiError("not_in_channel", {"error": "not_in_channel"})
        client.conversations_join.side_effect = SlackApiError("missing_scope", {"error": "missing_scope"})

        assert inbox_channel.invite_user_to_inbox(self.integration, "C1", "U1") is False

    @patch("posthog.models.integration.WebClient")
    def test_configured_channel_preserved_on_transient_error(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        set_default_slack_notification_channel(self.team.id, "C_CUSTOM|#alerts")
        client.conversations_info.side_effect = SlackApiError("ratelimited", {"error": "ratelimited"})

        result = inbox_channel.ensure_inbox_channel(self.integration)

        assert result == ("C_CUSTOM", "#alerts")
        client.conversations_create.assert_not_called()
        client.conversations_list.assert_not_called()
        assert get_default_slack_notification_channel(self.team.id) == "C_CUSTOM|#alerts"

    @patch("posthog.models.integration.WebClient")
    def test_configured_channel_replaced_when_definitely_gone(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        set_default_slack_notification_channel(self.team.id, "C_OLD|#alerts")
        client.conversations_info.side_effect = SlackApiError("channel_not_found", {"error": "channel_not_found"})
        client.conversations_list.return_value = {"channels": [], "response_metadata": {"next_cursor": ""}}
        client.conversations_create.return_value = {"channel": {"id": "C_NEW"}}

        result = inbox_channel.ensure_inbox_channel(self.integration)

        assert result == ("C_NEW", "#posthog-inbox")
        assert get_default_slack_notification_channel(self.team.id) == "C_NEW|#posthog-inbox"

    @patch("posthog.models.integration.WebClient")
    def test_ensure_returns_none_when_create_claimed_by_other(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        cache.add("slack_app:inbox_channel_create:v1:T12345", True, timeout=60)
        client.conversations_list.return_value = {"channels": [], "response_metadata": {"next_cursor": ""}}

        result = inbox_channel.ensure_inbox_channel(self.integration)

        assert result is None
        client.conversations_create.assert_not_called()

    @patch("posthog.models.integration.WebClient")
    def test_ensure_handles_conversations_list_error(self, mock_webclient_class):
        # name_taken sends us to the lookup; a transient list error there must fail closed (None).
        client = self._client(mock_webclient_class)
        client.conversations_create.side_effect = SlackApiError("name_taken", {"error": "name_taken"})
        client.conversations_list.side_effect = SlackApiError("ratelimited", {"error": "ratelimited"})

        result = inbox_channel.ensure_inbox_channel(self.integration)

        assert result is None

    @patch("posthog.models.integration.WebClient")
    def test_is_channel_member(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        client.conversations_members.return_value = {"members": ["U1", "U2"], "response_metadata": {"next_cursor": ""}}

        assert inbox_channel._is_channel_member(SlackIntegration(self.integration), "C1", "U1") is True
        assert inbox_channel._is_channel_member(SlackIntegration(self.integration), "C1", "U9") is False
