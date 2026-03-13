import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from posthog.models.integration import Integration, SlackIntegration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.api import resolve_slack_user
from products.slack_app.backend.models import SlackUserProfileCache


class TestResolveSlackUser:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        cache.clear()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-1")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)

        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack-posthog-code",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-test"},
        )

    @patch("posthog.models.integration.WebClient")
    def test_success(self, mock_webclient_class):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.return_value = {"user": {"profile": {"email": "dev@example.com", "display_name": "Dev"}}}

        slack = SlackIntegration(self.integration)
        result = resolve_slack_user(slack, self.integration, "U123", "C001", "1234.5678")

        assert result is not None
        assert result.user.email == "dev@example.com"
        assert result.slack_email == "dev@example.com"

    @patch("posthog.models.integration.WebClient")
    def test_missing_email(self, mock_webclient_class):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.return_value = {"user": {"profile": {}}}

        slack = SlackIntegration(self.integration)
        result = resolve_slack_user(slack, self.integration, "U123", "C001", "1234.5678")

        assert result is None
        mock_client.chat_postMessage.assert_called_once()
        assert "email" in mock_client.chat_postMessage.call_args.kwargs["text"].lower()

    @patch("posthog.models.integration.WebClient")
    def test_no_org_membership(self, mock_webclient_class):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.return_value = {"user": {"profile": {"email": "stranger@example.com"}}}

        slack = SlackIntegration(self.integration)
        result = resolve_slack_user(slack, self.integration, "U123", "C001", "1234.5678")

        assert result is None
        call_text = mock_client.chat_postEphemeral.call_args.kwargs["text"]
        assert "stranger@example.com" in call_text

    @patch("posthog.models.integration.WebClient")
    @patch("products.slack_app.backend.api.UserPermissions")
    def test_no_team_access(self, mock_permissions_class, mock_webclient_class):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.return_value = {"user": {"profile": {"email": "dev@example.com"}}}

        mock_permissions = MagicMock()
        mock_permissions.current_team.effective_membership_level = None
        mock_permissions_class.return_value = mock_permissions

        slack = SlackIntegration(self.integration)
        result = resolve_slack_user(slack, self.integration, "U123", "C001", "1234.5678")

        assert result is None
        call_text = mock_client.chat_postEphemeral.call_args.kwargs["text"]
        assert "access" in call_text.lower()

    @patch("posthog.models.integration.WebClient")
    def test_uses_db_cached_slack_profile(self, mock_webclient_class):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.side_effect = Exception("rate limited")

        SlackUserProfileCache.objects.create(
            integration=self.integration,
            slack_user_id="U123",
            email="dev@example.com",
            display_name="Dev",
            real_name="Developer",
        )

        slack = SlackIntegration(self.integration)
        result = resolve_slack_user(slack, self.integration, "U123", "C001", "1234.5678")

        assert result is not None
        assert result.user.email == "dev@example.com"
        assert result.slack_email == "dev@example.com"
        mock_client.users_info.assert_not_called()

    @patch("posthog.models.integration.WebClient")
    def test_persists_slack_profile_after_lookup(self, mock_webclient_class):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.return_value = {
            "user": {
                "profile": {
                    "email": "dev@example.com",
                    "display_name": "Dev",
                    "real_name": "Developer",
                }
            }
        }

        slack = SlackIntegration(self.integration)
        result = resolve_slack_user(slack, self.integration, "U123", "C001", "1234.5678")

        assert result is not None
        profile = SlackUserProfileCache.objects.get(integration=self.integration, slack_user_id="U123")
        assert profile.email == "dev@example.com"
        assert profile.display_name == "Dev"
        assert profile.real_name == "Developer"
