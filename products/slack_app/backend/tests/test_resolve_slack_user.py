from datetime import timedelta

import pytest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.models.integration import Integration, SlackIntegration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.api import resolve_slack_user
from products.slack_app.backend.models import SlackUserProfileCache
from products.slack_app.backend.services.slack_user_info import SLACK_USER_PROFILE_TTL, lookup_slack_user_id_by_email


class TestResolveSlackUser:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-1")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)

        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
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

    @pytest.mark.parametrize(
        "slack_email",
        [
            pytest.param("DEV@example.com", id="uppercase_local_part"),
            pytest.param("dev@Example.com", id="mixed_case_domain"),
            pytest.param("DEV@EXAMPLE.COM", id="all_uppercase"),
        ],
    )
    @patch("posthog.models.integration.WebClient")
    def test_matches_email_case_insensitively(self, mock_webclient_class, slack_email):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.return_value = {"user": {"profile": {"email": slack_email}}}

        slack = SlackIntegration(self.integration)
        result = resolve_slack_user(slack, self.integration, "U123", "C001", "1234.5678")

        assert result is not None
        assert result.user.email == "dev@example.com"
        assert result.slack_email == slack_email

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
        mock_client.chat_postEphemeral.assert_not_called()
        mock_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert call_kwargs["thread_ts"] == "1234.5678"
        assert "stranger@example.com" in call_kwargs["text"]

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
            refreshed_at=timezone.now(),
        )

        slack = SlackIntegration(self.integration)
        result = resolve_slack_user(slack, self.integration, "U123", "C001", "1234.5678")

        assert result is not None
        assert result.user.email == "dev@example.com"
        assert result.slack_email == "dev@example.com"
        mock_client.users_info.assert_not_called()

    @pytest.mark.parametrize(
        "stale_refreshed_at",
        [
            pytest.param(lambda: timezone.now() - SLACK_USER_PROFILE_TTL - timedelta(minutes=1), id="stale_by_ttl"),
            pytest.param(lambda: None, id="null_refreshed_at"),
        ],
    )
    @patch("posthog.models.integration.WebClient")
    def test_refetches_when_profile_is_stale(self, mock_webclient_class, stale_refreshed_at):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.return_value = {
            "user": {
                "is_admin": True,
                "is_owner": False,
                "profile": {"email": "dev@example.com", "display_name": "Dev (renamed)", "real_name": "Developer"},
            }
        }

        before = timezone.now()
        SlackUserProfileCache.objects.create(
            integration=self.integration,
            slack_user_id="U123",
            email="dev@example.com",
            display_name="Dev",
            real_name="Developer",
            refreshed_at=stale_refreshed_at(),
        )

        slack = SlackIntegration(self.integration)
        result = resolve_slack_user(slack, self.integration, "U123", "C001", "1234.5678")

        assert result is not None
        assert result.slack_email == "dev@example.com"
        mock_client.users_info.assert_called_once_with(user="U123")
        profile = SlackUserProfileCache.objects.get(integration=self.integration, slack_user_id="U123")
        assert profile.display_name == "Dev (renamed)"
        assert profile.is_admin is True
        assert profile.refreshed_at is not None and profile.refreshed_at >= before

    @patch("posthog.models.integration.WebClient")
    def test_persists_slack_profile_after_lookup(self, mock_webclient_class):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.return_value = {
            "user": {
                "is_admin": True,
                "is_owner": True,
                "profile": {
                    "email": "dev@example.com",
                    "display_name": "Dev",
                    "real_name": "Developer",
                },
            }
        }

        slack = SlackIntegration(self.integration)
        result = resolve_slack_user(slack, self.integration, "U123", "C001", "1234.5678")

        assert result is not None
        profile = SlackUserProfileCache.objects.get(integration=self.integration, slack_user_id="U123")
        assert profile.email == "dev@example.com"
        assert profile.display_name == "Dev"
        assert profile.real_name == "Developer"
        assert profile.is_admin is True
        assert profile.is_owner is True


class TestLookupSlackUserIdByEmail:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-test"},
        )

    @patch("posthog.models.integration.WebClient")
    def test_uses_db_cached_profile(self, mock_webclient_class):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client

        SlackUserProfileCache.objects.create(
            integration=self.integration,
            slack_user_id="U123",
            email="dev@example.com",
            refreshed_at=timezone.now(),
        )

        slack = SlackIntegration(self.integration)
        slack_user_id = lookup_slack_user_id_by_email(slack, self.integration, "dev@example.com")

        assert slack_user_id == "U123"
        mock_client.users_lookupByEmail.assert_not_called()

    @patch("posthog.models.integration.WebClient")
    def test_lookup_by_email_api(self, mock_webclient_class):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_lookupByEmail.return_value = {
            "ok": True,
            "user": {
                "id": "U456",
                "profile": {"email": "new@example.com", "display_name": "New", "real_name": "User"},
            },
        }

        slack = SlackIntegration(self.integration)
        slack_user_id = lookup_slack_user_id_by_email(slack, self.integration, "new@example.com")

        assert slack_user_id == "U456"
        profile = SlackUserProfileCache.objects.get(integration=self.integration, slack_user_id="U456")
        assert profile.email == "new@example.com"
        assert profile.refreshed_at is not None

    @pytest.mark.parametrize(
        "stale_refreshed_at",
        [
            pytest.param(lambda: timezone.now() - SLACK_USER_PROFILE_TTL - timedelta(minutes=1), id="stale_by_ttl"),
            pytest.param(lambda: None, id="null_refreshed_at"),
        ],
    )
    @patch("posthog.models.integration.WebClient")
    def test_refetches_email_lookup_when_profile_is_stale(self, mock_webclient_class, stale_refreshed_at):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_lookupByEmail.return_value = {
            "ok": True,
            "user": {
                "id": "U999",
                "profile": {"email": "dev@example.com", "display_name": "Dev", "real_name": "Developer"},
            },
        }

        before = timezone.now()
        SlackUserProfileCache.objects.create(
            integration=self.integration,
            slack_user_id="U123",
            email="dev@example.com",
            refreshed_at=stale_refreshed_at(),
        )

        slack = SlackIntegration(self.integration)
        slack_user_id = lookup_slack_user_id_by_email(slack, self.integration, "dev@example.com")

        assert slack_user_id == "U999"
        mock_client.users_lookupByEmail.assert_called_once()
        refreshed_profile = SlackUserProfileCache.objects.get(integration=self.integration, slack_user_id="U999")
        assert refreshed_profile.refreshed_at is not None and refreshed_profile.refreshed_at >= before
        # The orphan row for the previous Slack user ID is purged so subsequent
        # lookups land on the fresh row instead of re-firing the email lookup.
        assert not SlackUserProfileCache.objects.filter(integration=self.integration, slack_user_id="U123").exists()
