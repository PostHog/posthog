import json

import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.integration import Integration, SlackIntegration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.signals.backend.facade.api import set_default_slack_notification_channel
from products.slack_app.backend.feature_flags import ASSISTANT_REQUIRED_SCOPES
from products.slack_app.backend.services.slack_welcome_messages import (
    INBOX_AI_APPROVAL_ACTION_ID,
    INBOX_AI_APPROVAL_BLOCK_PREFIX,
    INBOX_CREATE_ACTION_ID,
    INBOX_JOIN_ACTION_ID,
    INBOX_SOURCES_BLOCK_PREFIX,
    INBOX_SOURCES_CHECKBOXES_ACTION,
    build_assistant_pane_welcome,
    build_channel_welcome,
    build_onboarding_dm,
    build_team_join_welcome,
)
from products.slack_app.backend.tests.helpers import action_ids, all_block_text, render_blocks, url_buttons

BUILDERS = [
    ("channel", build_channel_welcome),
    ("team_join", build_team_join_welcome),
]


# An install that granted everything, so the copy a snapshot files is the whole of it.
ASSISTANT_SCOPE_CONFIG = {"scope": ",".join(sorted(ASSISTANT_REQUIRED_SCOPES))}


def _integration(**config) -> Integration:
    # Unsaved: every builder reads `config` and `integration_id` only.
    return Integration(kind="slack", integration_id="T_WELCOME", config={**ASSISTANT_SCOPE_CONFIG, **config})


# Keyed by name rather than by builder so each snapshot is filed under a readable id.
@pytest.mark.parametrize("name", [name for name, _ in BUILDERS])
def test_welcome_copy(name, snapshot):
    build = dict(BUILDERS)[name]
    text, blocks = build(_integration(app_id="A_WELCOME"))

    assert snapshot == f"{text}\n\n---\n\n{render_blocks(blocks)}"


def test_assistant_pane_welcome_copy(snapshot):
    assert snapshot == build_assistant_pane_welcome()


def test_assistant_pane_welcome_names_no_slash_command():
    # The pane is a DM, where the slash commands are not reachable.
    assert "/posthog" not in build_assistant_pane_welcome()


def test_assistant_pane_welcome_carries_no_markup_the_container_drops():
    # Posted as `text`, which renders mrkdwn but no blocks, so a link or a block-only
    # construct would reach the reader as literal characters.
    pane = build_assistant_pane_welcome()

    assert "<" not in pane and ">" not in pane


class TestWelcomeMessages(SimpleTestCase):
    @parameterized.expand(BUILDERS)
    def test_links_the_home_tab_when_the_app_id_is_known(self, _name, build):
        _, blocks = build(_integration(app_id="A_WELCOME"))

        assert "<slack://app?team=T_WELCOME&id=A_WELCOME&tab=home|" in json.dumps(blocks)

    @parameterized.expand(BUILDERS)
    def test_names_the_home_tab_in_plain_words_without_an_app_id(self, _name, build):
        _, blocks = build(_integration())
        rendered = json.dumps(blocks)

        assert "Home tab" in rendered
        assert "slack://" not in rendered
        assert "None" not in rendered

    @parameterized.expand(BUILDERS)
    def test_asks_for_a_rating(self, _name, build):
        _, blocks = build(_integration(app_id="A_WELCOME"))
        rendered = json.dumps(blocks)

        assert ":thumbsup:" in rendered and ":thumbsdown:" in rendered

    @parameterized.expand(BUILDERS)
    def test_carries_fallback_text_for_the_notification(self, _name, build):
        text, blocks = build(_integration(app_id="A_WELCOME"))

        assert text
        # Slack drops `blocks` from a notification preview, so text that leaked mrkdwn or a
        # link would show as raw markup on a lock screen.
        assert "<" not in text and "*" not in text and "`" not in text
        assert blocks

    @parameterized.expand([("with_scopes", True), ("without_scopes", False)])
    def test_channel_welcome_points_at_dms_only_where_they_answer(self, _name, has_assistant_scopes):
        # Slack never delivers `message.im` to an install without the assistant scopes, so on
        # those workspaces the advice sends the reader to a bot that stays silent.
        scope = ",".join(ASSISTANT_REQUIRED_SCOPES) if has_assistant_scopes else "chat:write"
        _, blocks = build_channel_welcome(
            Integration(kind="slack", integration_id="T_WELCOME", config={"scope": scope})
        )

        assert ("DM me" in all_block_text(blocks)) is has_assistant_scopes


class TestOnboardingDm:
    """The install onboarding DM: which blocks each step renders, and what the copy says."""

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

    @patch("posthog.models.integration.slack.WebClient")
    def test_dm_join_button_when_channel_exists_with_scope(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        set_default_slack_notification_channel(self.team.id, "C1|#posthog-inbox")
        client.conversations_info.return_value = {"channel": {"id": "C1"}}

        _, blocks = build_onboarding_dm(self.integration, SlackIntegration(self.integration))

        assert INBOX_JOIN_ACTION_ID in action_ids(blocks)

    @patch("posthog.models.integration.slack.WebClient")
    def test_dm_instructions_when_channel_exists_without_scope(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        self.integration.config = {"scope": "chat:write"}
        self.integration.save()
        set_default_slack_notification_channel(self.team.id, "C1|#posthog-inbox")
        client.conversations_info.return_value = {"channel": {"id": "C1"}}

        _, blocks = build_onboarding_dm(self.integration, SlackIntegration(self.integration))

        assert INBOX_JOIN_ACTION_ID not in action_ids(blocks)
        assert "workspace" in all_block_text(blocks)

    @patch("posthog.models.integration.slack.WebClient")
    def test_dm_create_button_when_no_channel_with_scope(self, mock_webclient_class):
        self._client(mock_webclient_class)

        _, blocks = build_onboarding_dm(self.integration, SlackIntegration(self.integration))

        assert INBOX_CREATE_ACTION_ID in action_ids(blocks)

    @patch("posthog.models.integration.slack.WebClient")
    def test_dm_instructions_with_inbox_link_when_no_channel_no_scope(self, mock_webclient_class):
        self._client(mock_webclient_class)
        self.integration.config = {"scope": "chat:write"}
        self.integration.save()

        _, blocks = build_onboarding_dm(self.integration, SlackIntegration(self.integration))

        assert INBOX_CREATE_ACTION_ID not in action_ids(blocks)
        assert "/inbox" in all_block_text(blocks)

    @patch("posthog.models.integration.slack.WebClient")
    def test_build_dm_appends_github_button_when_missing(self, mock_webclient_class):
        self._client(mock_webclient_class)

        _, blocks = build_onboarding_dm(self.integration, SlackIntegration(self.integration), needs_github=True)

        urls = url_buttons(blocks)
        assert any(
            f"/integrations/connect/github/?project_id={self.team.id}" in u and "connect_from=slack" in u for u in urls
        )
        assert INBOX_CREATE_ACTION_ID in action_ids(blocks)

    @patch("posthog.models.integration.slack.WebClient")
    def test_build_dm_omits_join_when_already_member(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        set_default_slack_notification_channel(self.team.id, "C1|#posthog-inbox")
        client.conversations_info.return_value = {"channel": {"id": "C1"}}

        _, blocks = build_onboarding_dm(
            self.integration, SlackIntegration(self.integration), needs_github=False, already_in_channel=True
        )

        assert blocks != []
        assert INBOX_JOIN_ACTION_ID not in action_ids(blocks)

    @patch("posthog.models.integration.slack.WebClient")
    def test_build_dm_already_member_shows_only_github(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        set_default_slack_notification_channel(self.team.id, "C1|#posthog-inbox")
        client.conversations_info.return_value = {"channel": {"id": "C1"}}

        _, blocks = build_onboarding_dm(
            self.integration, SlackIntegration(self.integration), needs_github=True, already_in_channel=True
        )

        assert any("/integrations/connect/github/" in u for u in url_buttons(blocks))
        assert INBOX_JOIN_ACTION_ID not in action_ids(blocks)

    @patch("posthog.models.integration.slack.WebClient")
    def test_onboarding_dm_copy(self, mock_webclient_class, snapshot):
        self._client(mock_webclient_class)

        text, blocks = build_onboarding_dm(self.integration, SlackIntegration(self.integration), needs_github=True)

        # The connect link carries the team's autoincrement id, which differs every run. Anchored
        # on the query parameter, because a bare id substitution also rewrites the port number.
        rendered = render_blocks(blocks).replace(f"project_id={self.team.id}", "project_id=<team_id>")
        assert snapshot == f"{text}\n\n---\n\n{rendered}"

    @patch("posthog.models.integration.slack.WebClient")
    def test_build_dm_no_github_block_when_connected(self, mock_webclient_class):
        self._client(mock_webclient_class)

        _, blocks = build_onboarding_dm(self.integration, SlackIntegration(self.integration))

        assert not any("/integrations/connect/github" in u for u in url_buttons(blocks))

    @patch("posthog.models.integration.slack.WebClient")
    def test_build_dm_sources_inline_checkboxes(self, mock_webclient_class):
        self._client(mock_webclient_class)

        _, blocks = build_onboarding_dm(self.integration, SlackIntegration(self.integration))

        assert INBOX_SOURCES_CHECKBOXES_ACTION in action_ids(blocks)
        checkboxes = next(
            el for b in blocks if b["type"] == "actions" for el in b["elements"] if el.get("type") == "checkboxes"
        )
        # only the two built-in toggle sources, no Linear / GitHub issues
        assert {o["value"] for o in checkboxes["options"]} == {"error_tracking"}
        block = next(b for b in blocks if b.get("block_id", "").startswith(INBOX_SOURCES_BLOCK_PREFIX))
        assert block["block_id"] == f"{INBOX_SOURCES_BLOCK_PREFIX}:{self.integration.id}"
        assert "Choose what I watch" in all_block_text(blocks)

    @patch("posthog.models.integration.slack.WebClient")
    def test_build_dm_shows_done_steps_as_checks(self, mock_webclient_class):
        self._client(mock_webclient_class)

        _, blocks = build_onboarding_dm(self.integration, SlackIntegration(self.integration), already_in_channel=True)

        # done steps render as '✅' lines, not pruned
        text = all_block_text(blocks)
        assert "Connected" in text
        assert "Posting to #posthog-inbox" in text
        assert INBOX_SOURCES_CHECKBOXES_ACTION in action_ids(blocks)

    @patch("posthog.models.integration.slack.WebClient")
    def test_build_dm_omits_ai_approval_when_done(self, mock_webclient_class):
        self._client(mock_webclient_class)

        _, blocks = build_onboarding_dm(self.integration, SlackIntegration(self.integration), needs_github=True)

        assert "AI data processing" not in " ".join(str(b) for b in blocks)

    @patch("posthog.models.integration.slack.WebClient")
    def test_build_dm_always_returns_message_even_when_all_done(self, mock_webclient_class):
        self._client(mock_webclient_class)

        _, all_done = build_onboarding_dm(self.integration, SlackIntegration(self.integration), already_in_channel=True)

        assert all_done != []  # posted unconditionally on install
        assert INBOX_JOIN_ACTION_ID not in action_ids(all_done)
        assert not any("/integrations/connect/github" in u for u in url_buttons(all_done))

    @patch("posthog.models.integration.slack.WebClient")
    def test_build_dm_ai_approval_checkbox_for_admin_and_trails(self, mock_webclient_class):
        self._client(mock_webclient_class)

        text, blocks = build_onboarding_dm(
            self.integration,
            SlackIntegration(self.integration),
            needs_ai_approval=True,
            ai_approval_is_admin=True,
            needs_github=True,
        )

        # Admin gets an inline checkbox (no browser/url) — approval happens in Slack.
        assert INBOX_AI_APPROVAL_ACTION_ID in action_ids(blocks)
        assert not any("organization-details" in u for u in url_buttons(blocks))
        ai_block = next(b for b in blocks if b.get("block_id", "").startswith(INBOX_AI_APPROVAL_BLOCK_PREFIX))
        assert ai_block["elements"][0]["type"] == "checkboxes"
        assert "AI data processing" not in text  # fixed notification text, not the step copy

    @patch("posthog.models.integration.slack.WebClient")
    def test_build_dm_ai_approval_note_for_non_admin_no_button(self, mock_webclient_class):
        self._client(mock_webclient_class)

        _, blocks = build_onboarding_dm(
            self.integration, SlackIntegration(self.integration), needs_ai_approval=True, ai_approval_is_admin=False
        )

        assert INBOX_AI_APPROVAL_ACTION_ID not in action_ids(blocks)
        assert "Ask an org admin" in all_block_text(blocks)

    @patch("posthog.models.integration.slack.WebClient")
    def test_dm_leads_with_self_driving_intro(self, mock_webclient_class):
        self._client(mock_webclient_class)

        _, blocks = build_onboarding_dm(self.integration, SlackIntegration(self.integration), needs_github=True)

        assert blocks[0]["type"] == "section"
        assert "self-driving" in blocks[0]["text"]["text"]
        assert "first report" in all_block_text(blocks)
