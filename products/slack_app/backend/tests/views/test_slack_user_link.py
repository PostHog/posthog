"""Tests for ``products.slack_app.backend.views.slack_user_link``.

Covers the two backend views in the user-link OAuth ceremony: the authorize
entrypoint (``GET /complete/slack-link/start/``) and the OAuth callback
(``GET /complete/slack-link/``). Shared fixtures (``org_team_user``,
``workspace_integration``, ``link_user``) come from ``conftest.py`` two
levels up.
"""

import pytest
from unittest.mock import patch

from django.test import Client

from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.services.slack_user_oauth import (
    CallbackState,
    InviteToken,
    SlackIdentity,
    SlackUserOAuthError,
)
from products.slack_app.backend.tests.conftest import SLACK_TEAM_ID, SLACK_USER_ACCESS_TOKEN, SLACK_USER_ID


class TestAuthorizeView:
    @pytest.fixture
    def logged_in_client(self, org_team_user):
        _, _, user = org_team_user
        client = Client()
        client.force_login(user)
        return client, user

    # All failure paths in the authorize view round-trip the user back to
    # Personal integrations with a `slack_link_error=<reason>` query param —
    # mirrors `personal_finish.github_link_complete`. The frontend toast
    # handler in `personalIntegrationsLogic.afterMount` renders the toast.

    def _assert_settings_redirect_error(self, response, expected_reason: str) -> None:
        assert response.status_code == 302
        assert response["Location"].startswith("/settings/user-personal-integrations?")
        assert f"slack_link_error={expected_reason}" in response["Location"]

    def test_missing_state_redirects_with_invalid_state_error(self, logged_in_client):
        client, _ = logged_in_client
        response = client.get("/complete/slack-link/start/")
        self._assert_settings_redirect_error(response, "invalid_state")

    def test_bad_state_redirects_with_invalid_state_error(self, logged_in_client):
        client, _ = logged_in_client
        response = client.get("/complete/slack-link/start/?state=garbage")
        self._assert_settings_redirect_error(response, "invalid_state")

    def test_unknown_workspace_redirects_with_workspace_not_found(self, logged_in_client, org_team_user):
        client, _ = logged_in_client
        token = InviteToken(
            slack_user_id=SLACK_USER_ID,
            slack_team_id="T-DOES-NOT-EXIST",
            posthog_team_id=999_999,
        ).encode()
        response = client.get(f"/complete/slack-link/start/?state={token}")
        self._assert_settings_redirect_error(response, "workspace_not_found")

    def test_flag_off_redirects_with_flag_off_error(self, logged_in_client, workspace_integration):
        client, _ = logged_in_client
        token = InviteToken(
            slack_user_id=SLACK_USER_ID,
            slack_team_id=SLACK_TEAM_ID,
            posthog_team_id=workspace_integration.team_id,
        ).encode()
        with patch("products.slack_app.backend.views.slack_user_link.is_slack_app_oauth_enabled", return_value=False):
            response = client.get(f"/complete/slack-link/start/?state={token}")
        self._assert_settings_redirect_error(response, "flag_off")

    def test_flag_on_redirects_to_slack_with_user_scope(self, logged_in_client, workspace_integration):
        client, _ = logged_in_client
        token = InviteToken(
            slack_user_id=SLACK_USER_ID,
            slack_team_id=SLACK_TEAM_ID,
            posthog_team_id=workspace_integration.team_id,
            channel="C001",
            thread_ts="1.2",
        ).encode()
        with (
            patch("products.slack_app.backend.views.slack_user_link.is_slack_app_oauth_enabled", return_value=True),
            patch(
                "products.slack_app.backend.services.slack_user_oauth.get_instance_settings",
                return_value={"SLACK_APP_CLIENT_ID": "cid", "SLACK_APP_CLIENT_SECRET": "csecret"},
            ),
        ):
            response = client.get(f"/complete/slack-link/start/?state={token}")
        assert response.status_code == 302
        location = response["Location"]
        assert location.startswith("https://slack.com/oauth/v2/authorize?")
        # The whole point: user_scope is requested, bot scopes stay empty.
        assert "user_scope=identity.basic" in location
        assert "scope=&" in location or location.endswith("scope=")

    def test_unauthenticated_user_is_bounced_through_login(self, db):
        # `db` fixture: PostHog's `login_required` consults `User.objects.exists()`
        # before deciding what to do for anonymous traffic, so an empty test DB
        # is the minimum requirement even though this case never touches the
        # view body.
        client = Client()
        response = client.get("/complete/slack-link/start/?state=anything")
        assert response.status_code in (302, 303)


class TestCallbackView:
    @pytest.fixture
    def logged_in_client(self, org_team_user):
        _, _, user = org_team_user
        client = Client()
        client.force_login(user)
        return client, user

    def _state_for(self, user, posthog_team_id, *, slack_team_id=SLACK_TEAM_ID, slack_user_id=SLACK_USER_ID):
        return CallbackState(
            slack_user_id=slack_user_id,
            slack_team_id=slack_team_id,
            posthog_team_id=posthog_team_id,
            posthog_user_id=user.id,
            channel="C001",
            thread_ts="1.2",
        ).encode()

    def _identity(self, **overrides) -> SlackIdentity:
        defaults: dict = {
            "slack_user_id": SLACK_USER_ID,
            "slack_team_id": SLACK_TEAM_ID,
            "slack_team_name": "My Workspace",
            "slack_email": "dev@slack.example",
            "user_access_token": SLACK_USER_ACCESS_TOKEN,
        }
        defaults.update(overrides)
        return SlackIdentity(**defaults)

    # All callback paths — success and error — round-trip to Personal
    # integrations with `slack_link_success=1` or `slack_link_error=<reason>`
    # so the frontend toast handler surfaces the result next to the linked
    # row that just appeared (or didn't).

    def _assert_settings_redirect_error(self, response, expected_reason: str) -> None:
        assert response.status_code == 302
        assert response["Location"].startswith("/settings/user-personal-integrations?")
        assert f"slack_link_error={expected_reason}" in response["Location"]

    def _assert_settings_redirect_success(self, response) -> None:
        assert response.status_code == 302
        assert response["Location"].startswith("/settings/user-personal-integrations?")
        assert "slack_link_success=1" in response["Location"]

    def test_missing_code_redirects_with_invalid_state(self, logged_in_client, workspace_integration):
        client, user = logged_in_client
        state = self._state_for(user, workspace_integration.team_id)
        response = client.get(f"/complete/slack-link/?state={state}")
        self._assert_settings_redirect_error(response, "invalid_state")

    def test_slack_error_param_is_passed_through(self, logged_in_client, workspace_integration):
        client, _ = logged_in_client
        response = client.get("/complete/slack-link/?error=access_denied&state=x")
        # Slack's error code propagates verbatim so the frontend toast can
        # render the friendly "Slack authorization was canceled." copy.
        self._assert_settings_redirect_error(response, "access_denied")

    def test_happy_path_creates_link_and_redirects_to_settings(self, logged_in_client, workspace_integration):
        client, user = logged_in_client
        state = self._state_for(user, workspace_integration.team_id)

        with (
            patch("products.slack_app.backend.views.slack_user_link.is_slack_app_oauth_enabled", return_value=True),
            patch("products.slack_app.backend.views.slack_user_link.exchange_code", return_value=self._identity()),
            patch("posthog.models.integration.WebClient"),
        ):
            response = client.get(f"/complete/slack-link/?code=abc&state={state}")

        self._assert_settings_redirect_success(response)
        link = UserIntegration.objects.get(user=user, kind=UserIntegration.IntegrationKind.SLACK)
        assert link.integration_id == SLACK_USER_ID
        assert link.config["slack_team_id"] == SLACK_TEAM_ID
        assert link.config["slack_team_name"] == "My Workspace"
        assert link.config["slack_email_at_link"] == "dev@slack.example"
        # The user access token IS persisted (mirrors the GitHub personal flow).
        assert link.sensitive_config == {"user_access_token": SLACK_USER_ACCESS_TOKEN}

    def test_team_mismatch_refuses_to_link(self, logged_in_client, workspace_integration):
        client, user = logged_in_client
        state = self._state_for(user, workspace_integration.team_id)

        with (
            patch("products.slack_app.backend.views.slack_user_link.is_slack_app_oauth_enabled", return_value=True),
            patch(
                "products.slack_app.backend.views.slack_user_link.exchange_code",
                return_value=self._identity(slack_team_id="T-DIFFERENT", slack_team_name=None, slack_email=None),
            ),
        ):
            response = client.get(f"/complete/slack-link/?code=abc&state={state}")

        self._assert_settings_redirect_error(response, "team_mismatch")
        # No row should have been written.
        assert not UserIntegration.objects.filter(user=user, kind=UserIntegration.IntegrationKind.SLACK).exists()

    def test_oauth_exchange_failure_redirects_with_exchange_failed(self, logged_in_client, workspace_integration):
        client, user = logged_in_client
        state = self._state_for(user, workspace_integration.team_id)

        with (
            patch("products.slack_app.backend.views.slack_user_link.is_slack_app_oauth_enabled", return_value=True),
            patch(
                "products.slack_app.backend.views.slack_user_link.exchange_code",
                side_effect=SlackUserOAuthError("invalid_code"),
            ),
        ):
            response = client.get(f"/complete/slack-link/?code=abc&state={state}")

        self._assert_settings_redirect_error(response, "exchange_failed")
        assert not UserIntegration.objects.filter(user=user).exists()

    def test_session_mismatch_refuses_to_link(self, org_team_user, workspace_integration):
        # CSRF guard: the attacker starts the OAuth dance themselves so
        # `state.posthog_user_id` points at the attacker, but the callback
        # fires in a *different* PostHog user's browser session (the victim,
        # who clicked a forwarded URL). The link MUST NOT be written against
        # the victim's account. Without this check, the attacker's Slack id
        # would be bound to the victim and every future @mention from the
        # attacker would route to them.
        _, _, victim = org_team_user
        attacker = User.objects.create(email="attacker@example.com", distinct_id="attacker-1")
        client = Client()
        client.force_login(victim)
        # State carries the *attacker's* posthog_user_id (the flow's initiator),
        # but the callback is hitting the victim's session.
        state = self._state_for(attacker, workspace_integration.team_id)

        with (
            patch("products.slack_app.backend.views.slack_user_link.is_slack_app_oauth_enabled", return_value=True),
            patch("products.slack_app.backend.views.slack_user_link.exchange_code", return_value=self._identity()),
        ):
            response = client.get(f"/complete/slack-link/?code=abc&state={state}")

        self._assert_settings_redirect_error(response, "session_mismatch")
        # No row written against either user.
        assert not UserIntegration.objects.filter(kind=UserIntegration.IntegrationKind.SLACK).exists()

    def test_org_mismatch_refuses_to_link(self, workspace_integration, db):
        # A user logged into PostHog but NOT a member of the workspace's org —
        # e.g. someone who got hold of a forwarded invite URL. The OAuth dance
        # itself can complete (they have a valid session, Slack auth works),
        # but we refuse the write so orphan rows can't accumulate.
        outsider = User.objects.create(email="outsider@example.com", distinct_id="outsider-1")
        client = Client()
        client.force_login(outsider)
        state = self._state_for(outsider, workspace_integration.team_id)

        with (
            patch("products.slack_app.backend.views.slack_user_link.is_slack_app_oauth_enabled", return_value=True),
            patch("products.slack_app.backend.views.slack_user_link.exchange_code", return_value=self._identity()),
        ):
            response = client.get(f"/complete/slack-link/?code=abc&state={state}")

        self._assert_settings_redirect_error(response, "org_mismatch")
        assert not UserIntegration.objects.filter(user=outsider).exists()
