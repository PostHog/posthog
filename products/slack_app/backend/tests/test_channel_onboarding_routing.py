from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.test.client import RequestFactory

from posthog.helpers.slack_scopes import REQUIRED_SLACK_SCOPES
from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.api import (
    ROUTE_HANDLED_LOCALLY,
    ROUTE_NO_INTEGRATION,
    _channel_onboarding_cache_key,
    route_posthog_code_event_to_relevant_region,
)
from products.slack_app.backend.services.slack_auth import get_cached_auth_state


@override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
class TestMemberJoinedChannelRouting(TestCase):
    """Routing-level coverage for the channel onboarding flow.

    Each test patches ``SlackIntegration`` so we can assert against the Slack
    client without standing up a real WebClient. The Slack workspace row is
    real Postgres state — only the side-effecting Slack API is mocked.
    """

    BOT_USER_ID = "U_BOT"
    SLACK_TEAM_ID = "T12345"
    CHANNEL_ID = "C_NEW_CHANNEL"

    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-1")
        OrganizationMembership.objects.create(organization=self.organization, user=self.user)
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id=self.SLACK_TEAM_ID,
            config={"scope": ",".join(sorted(REQUIRED_SLACK_SCOPES))},
            sensitive_config={"access_token": "xoxb-test"},
        )
        # ``load_integrations`` now eagerly calls ``auth.test`` on cache miss.
        # These tests patch ``products.slack_app.backend.api.SlackIntegration``
        # but the resolver imports SlackIntegration from
        # ``posthog.models.integration`` directly, so the patch doesn't catch
        # the resolver's call. Pre-populate the cache with ``ok=true`` so the
        # resolver short-circuits; ``bot_user_id=None`` keeps
        # ``get_cached_bot_user_id`` falling through to the (mocked)
        # ``auth.test`` call the onboarding flow expects.
        from products.slack_app.backend.services.slack_auth import write_auth_state_ok

        write_auth_state_ok(self.integration.id, bot_user_id=None)

    def _request(self):
        return self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")

    def _event(self, *, user: str | None = None, channel: str | None = None) -> dict:
        return {
            "type": "member_joined_channel",
            "user": user if user is not None else self.BOT_USER_ID,
            "channel": channel if channel is not None else self.CHANNEL_ID,
            "channel_type": "C",
        }

    def _mock_slack(self, slack_cls_mock, *, bot_user_id: str | None = BOT_USER_ID, post_ok: bool = True):
        instance = MagicMock()
        instance.client.auth_test.return_value = {"user_id": bot_user_id}
        if post_ok:
            instance.client.chat_postMessage.return_value = {"ok": True}
        else:
            instance.client.chat_postMessage.side_effect = RuntimeError("slack down")
        slack_cls_mock.return_value = instance
        return instance

    @patch("products.slack_app.backend.api.SlackIntegration")
    def test_bot_joined_posts_onboarding_and_claims_dedupe(self, slack_cls):
        instance = self._mock_slack(slack_cls)

        result = route_posthog_code_event_to_relevant_region(self._request(), self._event(), self.SLACK_TEAM_ID)

        assert result == ROUTE_HANDLED_LOCALLY
        instance.client.chat_postMessage.assert_called_once()
        call_kwargs = instance.client.chat_postMessage.call_args.kwargs
        assert call_kwargs["channel"] == self.CHANNEL_ID
        assert any(block.get("type") == "actions" for block in call_kwargs["blocks"])
        # Dedupe slot is held so a Slack retry won't double-post.
        assert cache.get(_channel_onboarding_cache_key(self.SLACK_TEAM_ID, self.CHANNEL_ID)) is True

    @patch("products.slack_app.backend.api.SlackIntegration")
    def test_human_joined_does_not_post(self, slack_cls):
        instance = self._mock_slack(slack_cls)

        result = route_posthog_code_event_to_relevant_region(
            self._request(), self._event(user="U_HUMAN"), self.SLACK_TEAM_ID
        )

        assert result == ROUTE_HANDLED_LOCALLY
        instance.client.chat_postMessage.assert_not_called()
        assert cache.get(_channel_onboarding_cache_key(self.SLACK_TEAM_ID, self.CHANNEL_ID)) is None

    @patch("products.slack_app.backend.api.SlackIntegration")
    def test_duplicate_delivery_is_idempotent(self, slack_cls):
        instance = self._mock_slack(slack_cls)

        route_posthog_code_event_to_relevant_region(self._request(), self._event(), self.SLACK_TEAM_ID)
        route_posthog_code_event_to_relevant_region(self._request(), self._event(), self.SLACK_TEAM_ID)

        instance.client.chat_postMessage.assert_called_once()

    @patch("products.slack_app.backend.api.SlackIntegration")
    def test_ext_shared_channel_drops_silently_without_db_touch(self, slack_cls):
        """Onboarding never posts in externally-shared channels.

        The drop happens before workspace lookup, so ``SlackIntegration`` is
        never instantiated — asserting that catches future regressions that
        reorder the gate behind the DB query.
        """
        result = route_posthog_code_event_to_relevant_region(
            self._request(), self._event(), self.SLACK_TEAM_ID, is_ext_shared_channel=True
        )

        assert result == ROUTE_HANDLED_LOCALLY
        slack_cls.assert_not_called()

    @patch("products.slack_app.backend.api.SlackIntegration")
    def test_auth_test_failure_drops_silently(self, slack_cls):
        instance = MagicMock()
        instance.client.auth_test.side_effect = RuntimeError("auth down")
        slack_cls.return_value = instance

        result = route_posthog_code_event_to_relevant_region(self._request(), self._event(), self.SLACK_TEAM_ID)

        assert result == ROUTE_HANDLED_LOCALLY
        instance.client.chat_postMessage.assert_not_called()

    @patch("products.slack_app.backend.api.SlackIntegration")
    def test_post_failure_releases_dedupe_slot(self, slack_cls):
        self._mock_slack(slack_cls, post_ok=False)

        result = route_posthog_code_event_to_relevant_region(self._request(), self._event(), self.SLACK_TEAM_ID)

        assert result == ROUTE_HANDLED_LOCALLY
        # Slot released so a future retry can try again.
        assert cache.get(_channel_onboarding_cache_key(self.SLACK_TEAM_ID, self.CHANNEL_ID)) is None

    @patch("products.slack_app.backend.api.SlackIntegration")
    def test_no_workspace_integration_routes_no_integration(self, slack_cls):
        self.integration.delete()
        # Mark the request as already-proxied so the dispatcher drops instead
        # of trying to forward to the other region (which would hit the network).
        request = self.factory.post(
            "/slack/event-callback/",
            HTTP_HOST="us.posthog.com",
            headers={"X-PostHog-Region-Proxied": "1"},
        )

        result = route_posthog_code_event_to_relevant_region(request, self._event(), self.SLACK_TEAM_ID)

        assert result == ROUTE_NO_INTEGRATION
        slack_cls.assert_not_called()

    @patch("products.slack_app.backend.api.SlackIntegration")
    def test_bot_user_id_is_cached(self, slack_cls):
        instance = self._mock_slack(slack_cls)

        route_posthog_code_event_to_relevant_region(self._request(), self._event(), self.SLACK_TEAM_ID)
        # Second event in a different channel; auth.test should only have been
        # called once because the bot user id is cached per integration.
        route_posthog_code_event_to_relevant_region(self._request(), self._event(channel="C_OTHER"), self.SLACK_TEAM_ID)

        assert instance.client.auth_test.call_count == 1
        cached_state = get_cached_auth_state(self.integration.id)
        assert cached_state is not None
        assert cached_state.ok is True
        assert cached_state.bot_user_id == self.BOT_USER_ID
