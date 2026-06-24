"""Tests for ``products.slack_app.backend.services.slack_user_oauth``.

Covers the linked-user resolver, the Pydantic state models that flow through
Slack's OAuth redirects, and the ``resolve_slack_user`` integration in
``products.slack_app.backend.api`` that consumes them. Shared fixtures
(``org_team_user``, ``workspace_integration``, ``link_user``) come from
``conftest.py`` one level up.
"""

from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

from posthog.models.integration import SlackIntegration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.api import resolve_slack_user
from products.slack_app.backend.services.slack_user_oauth import (
    CallbackState,
    InviteToken,
    build_invite_url,
    find_linked_posthog_user,
)
from products.slack_app.backend.tests.conftest import SLACK_TEAM_ID, SLACK_USER_ID


class TestFindLinkedPosthogUser:
    def test_returns_linked_user_when_scoped_org_matches(self, org_team_user, link_user):
        org, _, user = org_team_user
        link_user(user, slack_team_name="Test Workspace", slack_email_at_link="dev@example.com")
        found = find_linked_posthog_user(
            slack_user_id=SLACK_USER_ID, slack_team_id=SLACK_TEAM_ID, candidate_org_ids={org.id}
        )
        assert found is not None
        assert found.id == user.id

    def test_returns_none_when_team_id_does_not_match(self, org_team_user, link_user):
        org, _, user = org_team_user
        link_user(user)
        assert (
            find_linked_posthog_user(slack_user_id=SLACK_USER_ID, slack_team_id="T-OTHER", candidate_org_ids={org.id})
            is None
        )

    def test_returns_none_when_user_is_in_different_org(self, org_team_user, link_user):
        _, _, user = org_team_user
        link_user(user)
        other_org = Organization.objects.create(name="Unrelated")
        assert (
            find_linked_posthog_user(
                slack_user_id=SLACK_USER_ID, slack_team_id=SLACK_TEAM_ID, candidate_org_ids={other_org.id}
            )
            is None
        )

    def test_returns_none_when_no_link_exists(self, org_team_user):
        org, _, _ = org_team_user
        assert (
            find_linked_posthog_user(
                slack_user_id=SLACK_USER_ID, slack_team_id=SLACK_TEAM_ID, candidate_org_ids={org.id}
            )
            is None
        )

    def test_empty_inputs_return_none(self):
        # Use a sentinel UUID for the non-empty-set arg since the function
        # signature is `set[UUID]`; the value is never looked up because the
        # early-return guards on empty slack_user_id / slack_team_id fire first.
        sentinel_org_id = uuid4()
        assert (
            find_linked_posthog_user(slack_user_id="", slack_team_id=SLACK_TEAM_ID, candidate_org_ids={sentinel_org_id})
            is None
        )
        assert (
            find_linked_posthog_user(slack_user_id=SLACK_USER_ID, slack_team_id="", candidate_org_ids={sentinel_org_id})
            is None
        )
        assert (
            find_linked_posthog_user(slack_user_id=SLACK_USER_ID, slack_team_id=SLACK_TEAM_ID, candidate_org_ids=set())
            is None
        )

    def test_multiple_linked_users_returns_most_recent_accessible(self, org_team_user, link_user):
        org, _, first_user = org_team_user
        # Two PostHog accounts in the same org, both linked to the same Slack identity.
        # The DB allows this; the resolver tiebreaks deterministically on
        # `-created_at` (most recently linked wins).
        second_user = User.objects.create(email="dev2@example.com", distinct_id="user-2")
        OrganizationMembership.objects.create(user=second_user, organization=org)
        link_user(first_user)
        link_user(second_user)

        found = find_linked_posthog_user(
            slack_user_id=SLACK_USER_ID, slack_team_id=SLACK_TEAM_ID, candidate_org_ids={org.id}
        )
        assert found is not None
        assert found.id == second_user.id

    def test_most_recent_link_skipped_when_user_lacks_org_membership(self, org_team_user, link_user):
        org, _, first_user = org_team_user
        # `first_user` is in `org`; `second_user` is in `unrelated_org`. With
        # candidate_org_ids={org.id}, only `first_user` qualifies even though
        # `second_user` linked more recently. Resolver must walk past the
        # most-recent link rather than refusing to match.
        unrelated_org = Organization.objects.create(name="Unrelated")
        second_user = User.objects.create(email="dev2@example.com", distinct_id="user-2")
        OrganizationMembership.objects.create(user=second_user, organization=unrelated_org)
        link_user(first_user)
        link_user(second_user)

        found = find_linked_posthog_user(
            slack_user_id=SLACK_USER_ID, slack_team_id=SLACK_TEAM_ID, candidate_org_ids={org.id}
        )
        assert found is not None
        assert found.id == first_user.id


class TestUserSlackIntegrationFromIdentity:
    """Tests for the model factory that the OAuth callback hands off to.

    Lives with the service tests because the factory is tightly coupled to
    the OAuth-flow output shape (``SlackIdentity`` fields → ``UserIntegration``
    row), even though the function itself is defined under ``posthog.models``.
    """

    def test_creates_row_with_stored_user_token(self, org_team_user, link_user):
        _, _, user = org_team_user
        integration = link_user(
            user,
            slack_team_name="Workspace",
            slack_email_at_link="dev@slack.example",
            user_access_token="xoxp-fresh",
        )
        assert integration.kind == UserIntegration.IntegrationKind.SLACK
        assert integration.integration_id == SLACK_USER_ID
        assert integration.config["slack_team_id"] == SLACK_TEAM_ID
        assert integration.config["slack_team_name"] == "Workspace"
        assert integration.config["slack_email_at_link"] == "dev@slack.example"
        # Token persisted in symmetry with the GitHub personal flow — future
        # "act as user" scopes can reuse it without a fresh OAuth consent.
        assert integration.sensitive_config == {"user_access_token": "xoxp-fresh"}

    def test_update_refreshes_token_in_place(self, org_team_user, link_user):
        _, _, user = org_team_user
        first = link_user(user, slack_team_name="Old name", user_access_token="xoxp-1")
        second = link_user(
            user,
            slack_team_name="New name",
            slack_email_at_link="dev@slack.example",
            user_access_token="xoxp-2",
        )
        assert first.id == second.id
        assert second.config["slack_team_name"] == "New name"
        assert second.sensitive_config == {"user_access_token": "xoxp-2"}


class TestResolveSlackUserWithLink:
    """Integration of ``api.resolve_slack_user`` with the linked-user lookup.

    Lives here rather than in ``tests/test_resolve_slack_user.py`` because the
    behavior under test is owned by the user-link service — the resolver just
    delegates the lookup to it.
    """

    @patch("posthog.models.integration.WebClient")
    @patch("products.slack_app.backend.api.slack_oauth_link_enabled")
    def test_flag_off_falls_through_to_email_path_unchanged(
        self, mock_flag, mock_webclient_class, org_team_user, workspace_integration, link_user
    ):
        _, _, user = org_team_user
        # Even with a link row present, flag-off behavior must not consult it.
        link_user(user)
        mock_flag.return_value = False
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.return_value = {"user": {"profile": {"email": "dev@example.com"}}}

        result = resolve_slack_user(
            SlackIntegration(workspace_integration), workspace_integration, SLACK_USER_ID, "C001", "1234.5"
        )

        assert result is not None
        # users.info IS called — confirms email path ran.
        assert mock_client.users_info.called
        assert result.slack_email == "dev@example.com"

    @patch("posthog.models.integration.WebClient")
    @patch("products.slack_app.backend.api.slack_oauth_link_enabled")
    def test_flag_on_with_link_short_circuits_email_lookup(
        self, mock_flag, mock_webclient_class, org_team_user, workspace_integration, link_user
    ):
        _, _, user = org_team_user
        link_user(user)
        mock_flag.return_value = True
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client

        result = resolve_slack_user(
            SlackIntegration(workspace_integration), workspace_integration, SLACK_USER_ID, "C001", "1234.5"
        )

        assert result is not None
        assert result.user.id == user.id
        # The whole point: no Slack API hit when a link exists.
        mock_client.users_info.assert_not_called()
        # And the contract: slack_email is None on the linked path.
        assert result.slack_email is None

    # `test_flag_on_with_link_but_no_team_access_returns_none` lives at
    # `tests/test_zz_resolve_slack_user_with_link_no_access.py` — see that
    # file's module docstring for why it can't live next to its siblings here.

    @patch("posthog.models.integration.WebClient")
    @patch("products.slack_app.backend.api.post_link_invite_message")
    @patch("products.slack_app.backend.api.slack_oauth_link_enabled")
    def test_flag_on_with_no_link_and_no_membership_posts_invite(
        self,
        mock_flag,
        mock_post_invite,
        mock_webclient_class,
        org_team_user,
        workspace_integration,
    ):
        mock_flag.return_value = True
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.return_value = {"user": {"profile": {"email": "stranger@example.com"}}}

        with patch("products.slack_app.backend.api.settings") as mock_settings:
            mock_settings.DEBUG = False
            result = resolve_slack_user(
                SlackIntegration(workspace_integration),
                workspace_integration,
                SLACK_USER_ID,
                "C001",
                "1234.5",
            )

        assert result is None
        # Two messages by design: a public thread reply explaining the failure
        # to the rest of the channel, plus an ephemeral button visible only
        # to the affected user. Confirming both fire — neither is redundant
        # because their audiences differ.
        assert mock_client.chat_postMessage.called or mock_client.chat_postEphemeral.called
        mock_post_invite.assert_called_once()
        invite_kwargs = mock_post_invite.call_args.kwargs
        assert invite_kwargs["slack_user_id"] == SLACK_USER_ID
        assert invite_kwargs["slack_email"] == "stranger@example.com"
        assert invite_kwargs["invite_url"].startswith("http")

    @patch("posthog.models.integration.WebClient")
    @patch("products.slack_app.backend.api.post_link_invite_message")
    @patch("products.slack_app.backend.api.slack_oauth_link_enabled")
    def test_flag_off_with_no_membership_does_not_post_invite(
        self,
        mock_flag,
        mock_post_invite,
        mock_webclient_class,
        org_team_user,
        workspace_integration,
    ):
        mock_flag.return_value = False
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.return_value = {"user": {"profile": {"email": "stranger@example.com"}}}

        with patch("products.slack_app.backend.api.settings") as mock_settings:
            mock_settings.DEBUG = False
            result = resolve_slack_user(
                SlackIntegration(workspace_integration),
                workspace_integration,
                SLACK_USER_ID,
                "C001",
                "1234.5",
            )

        assert result is None
        mock_post_invite.assert_not_called()


@pytest.mark.django_db(transaction=False)
class TestInviteToken:
    def test_round_trips(self):
        original = InviteToken(
            slack_user_id=SLACK_USER_ID,
            slack_team_id=SLACK_TEAM_ID,
            posthog_team_id=42,
            channel="C001",
            thread_ts="1.2",
        )
        decoded = InviteToken.decode(original.encode())
        assert decoded == original

    def test_settings_initiated_invite_omits_slack_user_id(self):
        original = InviteToken(slack_team_id=SLACK_TEAM_ID, posthog_team_id=42)
        decoded = InviteToken.decode(original.encode())
        assert decoded is not None
        assert decoded.slack_user_id is None
        assert decoded.channel is None

    def test_rejects_tampered_token(self):
        token = InviteToken(slack_team_id=SLACK_TEAM_ID, posthog_team_id=42).encode()
        assert InviteToken.decode(token + "x") is None

    def test_rejects_callback_state_signed_with_other_salt(self):
        # A callback state must not satisfy the invite check (cross-salt).
        callback_state = CallbackState(slack_team_id="T1", posthog_team_id=1, posthog_user_id=99).encode()
        assert InviteToken.decode(callback_state) is None

    def test_invite_url_contains_signed_state(self):
        url = build_invite_url(
            slack_user_id=SLACK_USER_ID,
            slack_team_id=SLACK_TEAM_ID,
            posthog_team_id=42,
            channel=None,
            thread_ts=None,
        )
        assert "/complete/slack-link/start/?state=" in url


class TestCallbackState:
    def test_round_trips(self):
        original = CallbackState(slack_team_id="T1", posthog_team_id=1, posthog_user_id=99, slack_user_id="U1")
        decoded = CallbackState.decode(original.encode())
        assert decoded == original

    def test_rejects_invite_token(self):
        # Cross-salt protection in the other direction too.
        invite = InviteToken(slack_team_id="T1", posthog_team_id=1).encode()
        assert CallbackState.decode(invite) is None
