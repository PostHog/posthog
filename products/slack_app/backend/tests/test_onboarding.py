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
from products.slack_app.backend import onboarding


class TestOnboarding:
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

    def _action_ids(self, blocks):
        ids = [el["action_id"] for b in blocks if b["type"] == "actions" for el in b["elements"] if "action_id" in el]
        ids += [b["accessory"]["action_id"] for b in blocks if (b.get("accessory") or {}).get("action_id")]
        return ids

    def _url_buttons(self, blocks):
        urls = [el["url"] for b in blocks if b["type"] == "actions" for el in b["elements"] if "url" in el]
        urls += [b["accessory"]["url"] for b in blocks if (b.get("accessory") or {}).get("url")]
        return urls

    def _all_text(self, blocks):
        parts: list[str] = []
        for b in blocks:
            if (b.get("text") or {}).get("text"):
                parts.append(b["text"]["text"])
            for f in b.get("fields", []):
                parts.append(f.get("text", ""))
            for el in b.get("elements", []):
                txt = el.get("text")
                parts.append(txt if isinstance(txt, str) else (txt or {}).get("text", ""))
        return " ".join(parts)

    @patch("posthog.models.integration.WebClient")
    def test_dm_join_button_when_channel_exists_with_scope(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        set_default_slack_notification_channel(self.team.id, "C1|#posthog-inbox")
        client.conversations_info.return_value = {"channel": {"id": "C1"}}

        _, blocks = onboarding.build_onboarding_dm(self.integration, SlackIntegration(self.integration))

        assert onboarding.INBOX_JOIN_ACTION_ID in self._action_ids(blocks)

    @patch("posthog.models.integration.WebClient")
    def test_dm_instructions_when_channel_exists_without_scope(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        self.integration.config = {"scope": "chat:write"}
        self.integration.save()
        set_default_slack_notification_channel(self.team.id, "C1|#posthog-inbox")
        client.conversations_info.return_value = {"channel": {"id": "C1"}}

        _, blocks = onboarding.build_onboarding_dm(self.integration, SlackIntegration(self.integration))

        assert onboarding.INBOX_JOIN_ACTION_ID not in self._action_ids(blocks)
        assert "workspace" in self._all_text(blocks)

    @patch("posthog.models.integration.WebClient")
    def test_dm_create_button_when_no_channel_with_scope(self, mock_webclient_class):
        self._client(mock_webclient_class)

        _, blocks = onboarding.build_onboarding_dm(self.integration, SlackIntegration(self.integration))

        assert onboarding.INBOX_CREATE_ACTION_ID in self._action_ids(blocks)

    @patch("posthog.models.integration.WebClient")
    def test_dm_instructions_with_inbox_link_when_no_channel_no_scope(self, mock_webclient_class):
        self._client(mock_webclient_class)
        self.integration.config = {"scope": "chat:write"}
        self.integration.save()

        _, blocks = onboarding.build_onboarding_dm(self.integration, SlackIntegration(self.integration))

        assert onboarding.INBOX_CREATE_ACTION_ID not in self._action_ids(blocks)
        assert "/inbox" in self._all_text(blocks)

    @patch("posthog.models.integration.WebClient")
    def test_send_onboarding_dm_posts_each_call(self, mock_webclient_class):
        # No per-user dedupe — onboarding is sent once because the install hook fires once, not
        # because send_onboarding_dm suppresses repeats.
        client = self._client(mock_webclient_class)

        assert onboarding.send_onboarding_dm(self.integration, "U1") is True
        assert onboarding.send_onboarding_dm(self.integration, "U1") is True
        assert client.chat_postMessage.call_count == 2

    @patch("posthog.models.integration.WebClient")
    def test_send_onboarding_dm_skips_empty_user(self, mock_webclient_class):
        client = self._client(mock_webclient_class)

        assert onboarding.send_onboarding_dm(self.integration, "") is False
        client.chat_postMessage.assert_not_called()

    @patch("posthog.models.integration.WebClient")
    def test_run_install_onboarding_creates_invites_and_dms(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        self.integration.config = {"scope": "channels:manage,chat:write", "authed_user": {"id": "U_INSTALL"}}
        self.integration.save()
        client.conversations_list.return_value = {"channels": [], "response_metadata": {"next_cursor": ""}}
        client.conversations_create.return_value = {"channel": {"id": "C_NEW"}}
        client.conversations_info.return_value = {"channel": {"id": "C_NEW"}}

        onboarding.run_install_onboarding(self.integration)

        client.conversations_create.assert_called_once()
        client.conversations_invite.assert_called_once_with(channel="C_NEW", users="U_INSTALL")
        assert client.chat_postMessage.called
        assert get_default_slack_notification_channel(self.team.id) == "C_NEW|#posthog-inbox"

    @patch("posthog.models.integration.WebClient")
    def test_run_install_onboarding_noop_when_missing_scope(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        # No channels:manage scope -> onboarding is gated off for this install.
        self.integration.config = {"scope": "chat:write", "authed_user": {"id": "U_INSTALL"}}
        self.integration.save()

        onboarding.run_install_onboarding(self.integration)

        client.conversations_create.assert_not_called()
        client.chat_postMessage.assert_not_called()

    @patch("posthog.models.integration.WebClient")
    def test_send_onboarding_dm_returns_false_on_post_failure(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        client.chat_postMessage.side_effect = [
            SlackApiError("channel_not_found", {"error": "channel_not_found"}),
            {"ok": True},
        ]

        assert onboarding.send_onboarding_dm(self.integration, "U1") is False
        assert onboarding.send_onboarding_dm(self.integration, "U1") is True
        assert client.chat_postMessage.call_count == 2

    @patch("posthog.models.integration.WebClient")
    def test_build_dm_appends_github_button_when_missing(self, mock_webclient_class):
        self._client(mock_webclient_class)

        _, blocks = onboarding.build_onboarding_dm(
            self.integration, SlackIntegration(self.integration), needs_github=True
        )

        urls = self._url_buttons(blocks)
        assert any(
            f"/integrations/connect/github/?project_id={self.team.id}" in u and "connect_from=slack" in u for u in urls
        )
        assert onboarding.INBOX_CREATE_ACTION_ID in self._action_ids(blocks)

    @patch("posthog.models.integration.WebClient")
    def test_build_dm_omits_join_when_already_member(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        set_default_slack_notification_channel(self.team.id, "C1|#posthog-inbox")
        client.conversations_info.return_value = {"channel": {"id": "C1"}}

        _, blocks = onboarding.build_onboarding_dm(
            self.integration, SlackIntegration(self.integration), needs_github=False, already_in_channel=True
        )

        assert blocks != []
        assert onboarding.INBOX_JOIN_ACTION_ID not in self._action_ids(blocks)

    @patch("posthog.models.integration.WebClient")
    def test_build_dm_already_member_shows_only_github(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        set_default_slack_notification_channel(self.team.id, "C1|#posthog-inbox")
        client.conversations_info.return_value = {"channel": {"id": "C1"}}

        _, blocks = onboarding.build_onboarding_dm(
            self.integration, SlackIntegration(self.integration), needs_github=True, already_in_channel=True
        )

        assert any("/integrations/connect/github/" in u for u in self._url_buttons(blocks))
        assert onboarding.INBOX_JOIN_ACTION_ID not in self._action_ids(blocks)

    @patch("products.slack_app.backend.onboarding._has_enabled_source", return_value=True)
    @patch("products.slack_app.backend.onboarding._has_team_github", return_value=True)
    @patch("products.slack_app.backend.onboarding._has_personal_github", return_value=True)
    @patch("products.slack_app.backend.onboarding._resolve_onboarding_user", return_value=7)
    @patch("posthog.models.integration.WebClient")
    def test_send_onboarding_dm_posts_even_when_all_steps_satisfied(
        self, mock_webclient_class, _resolve, _personal, _team, _responder
    ):
        # Install-only delivery: always post, even if every step is already done (shown as '✅').
        client = self._client(mock_webclient_class)
        set_default_slack_notification_channel(self.team.id, "C1|#posthog-inbox")
        client.conversations_info.return_value = {"channel": {"id": "C1"}}
        client.conversations_members.return_value = {"members": ["U1"], "response_metadata": {"next_cursor": ""}}

        assert onboarding.send_onboarding_dm(self.integration, "U1") is True
        client.chat_postMessage.assert_called_once()

    @patch("posthog.models.integration.WebClient")
    def test_build_dm_no_github_block_when_connected(self, mock_webclient_class):
        self._client(mock_webclient_class)

        _, blocks = onboarding.build_onboarding_dm(self.integration, SlackIntegration(self.integration))

        assert not any("/integrations/connect/github" in u for u in self._url_buttons(blocks))

    @patch("products.slack_app.backend.onboarding._resolve_onboarding_user", return_value=123)
    @patch("products.slack_app.backend.onboarding._has_personal_github", return_value=False)
    @patch("products.slack_app.backend.onboarding._has_team_github", return_value=False)
    @patch("posthog.models.integration.WebClient")
    def test_send_onboarding_dm_includes_github_button(
        self, mock_webclient_class, _mock_team, _mock_personal, _mock_resolve
    ):
        client = self._client(mock_webclient_class)

        assert onboarding.send_onboarding_dm(self.integration, "U1") is True

        urls = self._url_buttons(client.chat_postMessage.call_args.kwargs["blocks"])
        assert any("/integrations/connect/github/" in u and "connect_from=slack" in u for u in urls)

    @patch("posthog.models.integration.WebClient")
    def test_build_dm_sources_inline_checkboxes(self, mock_webclient_class):
        self._client(mock_webclient_class)

        _, blocks = onboarding.build_onboarding_dm(self.integration, SlackIntegration(self.integration))

        assert onboarding.INBOX_SOURCES_CHECKBOXES_ACTION in self._action_ids(blocks)
        checkboxes = next(
            el for b in blocks if b["type"] == "actions" for el in b["elements"] if el.get("type") == "checkboxes"
        )
        # only the two built-in toggle sources, no Linear / GitHub issues
        assert {o["value"] for o in checkboxes["options"]} == {"error_tracking", "session_replay"}
        block = next(b for b in blocks if b.get("block_id", "").startswith(onboarding.INBOX_SOURCES_BLOCK_PREFIX))
        assert block["block_id"] == f"{onboarding.INBOX_SOURCES_BLOCK_PREFIX}:{self.integration.id}"
        assert "Choose what I watch" in self._all_text(blocks)

    @patch("posthog.models.integration.WebClient")
    def test_build_dm_shows_done_steps_as_checks(self, mock_webclient_class):
        self._client(mock_webclient_class)

        _, blocks = onboarding.build_onboarding_dm(
            self.integration, SlackIntegration(self.integration), already_in_channel=True
        )

        # done steps render as '✅' lines, not pruned
        text = self._all_text(blocks)
        assert "Connected" in text
        assert "Posting to #posthog-inbox" in text
        assert onboarding.INBOX_SOURCES_CHECKBOXES_ACTION in self._action_ids(blocks)

    @patch("posthog.models.integration.WebClient")
    def test_build_dm_omits_ai_approval_when_done(self, mock_webclient_class):
        self._client(mock_webclient_class)

        _, blocks = onboarding.build_onboarding_dm(
            self.integration, SlackIntegration(self.integration), needs_github=True
        )

        assert "AI data processing" not in " ".join(str(b) for b in blocks)

    @patch("posthog.models.integration.WebClient")
    def test_build_dm_always_returns_message_even_when_all_done(self, mock_webclient_class):
        self._client(mock_webclient_class)

        _, all_done = onboarding.build_onboarding_dm(
            self.integration, SlackIntegration(self.integration), already_in_channel=True
        )

        assert all_done != []  # posted unconditionally on install
        assert onboarding.INBOX_JOIN_ACTION_ID not in self._action_ids(all_done)
        assert not any("/integrations/connect/github" in u for u in self._url_buttons(all_done))

    @patch("products.slack_app.backend.onboarding._resolve_onboarding_user", return_value=None)
    @patch("posthog.models.integration.WebClient")
    def test_apply_sources_selection_syncs_checkboxes(self, mock_webclient_class, _resolve):
        from products.signals.backend.facade.api import has_enabled_source

        self._client(mock_webclient_class)
        _resolve.return_value = self.user.id

        assert onboarding.apply_sources_selection(self.integration, "U1", ["error_tracking"]) == []
        assert has_enabled_source(self.team.id) is True

        # unticking everything turns them back off (set-semantics)
        onboarding.apply_sources_selection(self.integration, "U1", [])
        assert has_enabled_source(self.team.id) is False

    @patch("products.slack_app.backend.onboarding._resolve_onboarding_user", return_value=None)
    @patch("posthog.models.integration.WebClient")
    def test_apply_sources_blocks_session_replay_without_ai_approval(self, mock_webclient_class, _resolve):
        from products.signals.backend.facade.api import has_enabled_source

        self._client(mock_webclient_class)
        _resolve.return_value = self.user.id
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

        blocked = onboarding.apply_sources_selection(self.integration, "U1", ["session_replay"])

        assert blocked == ["Session replay analysis"]  # surfaced so the handler can nudge the user
        assert has_enabled_source(self.team.id) is False

    @patch("products.slack_app.backend.services.inbox_interactivity._post_ephemeral_via_response_url")
    @patch("products.slack_app.backend.onboarding._resolve_onboarding_user", return_value=None)
    @patch("posthog.models.integration.WebClient")
    def test_sources_handler_nudges_when_session_replay_blocked(self, mock_webclient_class, _resolve, mock_ephemeral):
        from products.slack_app.backend.services import inbox_interactivity

        self._client(mock_webclient_class)
        _resolve.return_value = self.user.id
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        payload = {
            "team": {"id": "T12345"},
            "user": {"id": "U1"},
            "response_url": "https://hook",
            "actions": [
                {
                    "action_id": onboarding.INBOX_SOURCES_CHECKBOXES_ACTION,
                    "block_id": f"{onboarding.INBOX_SOURCES_BLOCK_PREFIX}:{self.integration.id}",
                    "selected_options": [{"value": "session_replay"}],
                }
            ],
        }

        inbox_interactivity.handle_inbox_sources(payload)

        mock_ephemeral.assert_called_once()
        assert "Approve AI data processing" in mock_ephemeral.call_args.args[1]

    def test_set_sources_error_tracking_no_approval_needed(self):
        from products.signals.backend.facade.api import has_enabled_source, set_sources

        assert has_enabled_source(self.team.id) is False
        assert set_sources(self.team.id, None, ["error_tracking"]) == []
        assert has_enabled_source(self.team.id) is True

    def test_set_sources_session_replay_blocked_without_ai_approval(self):
        from products.signals.backend.facade.api import has_enabled_source, set_sources

        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

        assert set_sources(self.team.id, None, ["session_replay"]) == ["Session replay analysis"]
        assert has_enabled_source(self.team.id) is False

    def test_set_sources_keeps_enabled_source_when_ai_later_revoked(self):
        from products.signals.backend.facade.api import has_enabled_source, set_sources

        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        assert set_sources(self.team.id, None, ["session_replay"]) == []
        assert has_enabled_source(self.team.id) is True

        # AI revoked: re-submitting the still-ticked selection must leave it enabled, not disable it.
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        assert set_sources(self.team.id, None, ["session_replay"]) == ["Session replay analysis"]
        assert has_enabled_source(self.team.id) is True

    @patch("posthog.models.integration.WebClient")
    def test_build_dm_ai_approval_checkbox_for_admin_and_trails(self, mock_webclient_class):
        self._client(mock_webclient_class)

        text, blocks = onboarding.build_onboarding_dm(
            self.integration,
            SlackIntegration(self.integration),
            needs_ai_approval=True,
            ai_approval_is_admin=True,
            needs_github=True,
        )

        # Admin gets an inline checkbox (no browser/url) — approval happens in Slack.
        assert onboarding.INBOX_AI_APPROVAL_ACTION_ID in self._action_ids(blocks)
        assert not any("organization-details" in u for u in self._url_buttons(blocks))
        ai_block = next(
            b for b in blocks if b.get("block_id", "").startswith(onboarding.INBOX_AI_APPROVAL_BLOCK_PREFIX)
        )
        assert ai_block["elements"][0]["type"] == "checkboxes"
        assert "AI data processing" not in text  # fixed notification text, not the step copy

    @patch("posthog.models.integration.WebClient")
    def test_build_dm_ai_approval_note_for_non_admin_no_button(self, mock_webclient_class):
        self._client(mock_webclient_class)

        _, blocks = onboarding.build_onboarding_dm(
            self.integration, SlackIntegration(self.integration), needs_ai_approval=True, ai_approval_is_admin=False
        )

        assert onboarding.INBOX_AI_APPROVAL_ACTION_ID not in self._action_ids(blocks)
        assert "Ask an org admin" in self._all_text(blocks)

    def test_has_ai_approval_reflects_org(self):
        assert onboarding._has_ai_approval(self.team.id) is True  # default-approved org
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        assert onboarding._has_ai_approval(self.team.id) is False

    @patch("products.slack_app.backend.onboarding._is_org_admin", return_value=True)
    @patch("products.slack_app.backend.onboarding._resolve_onboarding_user", return_value=7)
    @patch("posthog.models.integration.WebClient")
    def test_approve_ai_data_processing_admin_sets_org_flag(self, mock_webclient_class, _resolve, _admin):
        self._client(mock_webclient_class)
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

        ok = onboarding.approve_ai_data_processing(self.integration, "U1")

        assert ok is True
        self.organization.refresh_from_db()
        assert self.organization.is_ai_data_processing_approved is True

    @patch("products.slack_app.backend.onboarding._is_org_admin", return_value=False)
    @patch("products.slack_app.backend.onboarding._resolve_onboarding_user", return_value=7)
    @patch("posthog.models.integration.WebClient")
    def test_approve_ai_data_processing_non_admin_rejected(self, mock_webclient_class, _resolve, _admin):
        self._client(mock_webclient_class)
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

        ok = onboarding.approve_ai_data_processing(self.integration, "U1")

        assert ok is False
        self.organization.refresh_from_db()
        assert self.organization.is_ai_data_processing_approved is False

    @patch("products.slack_app.backend.onboarding._is_org_admin", return_value=True)
    @patch("products.slack_app.backend.onboarding._has_enabled_source", return_value=True)
    @patch("products.slack_app.backend.onboarding._has_team_github", return_value=True)
    @patch("products.slack_app.backend.onboarding._has_personal_github", return_value=True)
    @patch("products.slack_app.backend.onboarding._resolve_onboarding_user", return_value=7)
    @patch("posthog.models.integration.WebClient")
    def test_send_onboarding_dm_gates_on_ai_approval_admin(
        self, mock_webclient_class, _resolve, _personal, _team, _responder, _admin
    ):
        client = self._client(mock_webclient_class)
        set_default_slack_notification_channel(self.team.id, "C1|#posthog-inbox")
        client.conversations_info.return_value = {"channel": {"id": "C1"}}
        client.conversations_members.return_value = {"members": ["U1"], "response_metadata": {"next_cursor": ""}}
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

        # Everything else satisfied, but the unapproved org still triggers a DM — admin gets the button.
        assert onboarding.send_onboarding_dm(self.integration, "U1") is True
        blocks = client.chat_postMessage.call_args.kwargs["blocks"]
        assert onboarding.INBOX_AI_APPROVAL_ACTION_ID in self._action_ids(blocks)

    @patch("products.slack_app.backend.onboarding._is_org_admin", return_value=False)
    @patch("products.slack_app.backend.onboarding._has_enabled_source", return_value=True)
    @patch("products.slack_app.backend.onboarding._has_team_github", return_value=True)
    @patch("products.slack_app.backend.onboarding._has_personal_github", return_value=True)
    @patch("products.slack_app.backend.onboarding._resolve_onboarding_user", return_value=7)
    @patch("posthog.models.integration.WebClient")
    def test_send_onboarding_dm_non_admin_gets_note_not_button(
        self, mock_webclient_class, _resolve, _personal, _team, _responder, _admin
    ):
        client = self._client(mock_webclient_class)
        set_default_slack_notification_channel(self.team.id, "C1|#posthog-inbox")
        client.conversations_info.return_value = {"channel": {"id": "C1"}}
        client.conversations_members.return_value = {"members": ["U1"], "response_metadata": {"next_cursor": ""}}
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

        # A member can't approve, so they get an informational note (no button) and aren't blocked.
        assert onboarding.send_onboarding_dm(self.integration, "U1") is True
        blocks = client.chat_postMessage.call_args.kwargs["blocks"]
        assert onboarding.INBOX_AI_APPROVAL_ACTION_ID not in self._action_ids(blocks)
        assert "Ask an org admin" in self._all_text(blocks)

    def test_slack_event_props_bundle(self):
        from products.slack_app.backend.analytics import slack_event_props

        props = slack_event_props(self.integration, slack_user_id="U1", foo="bar")

        assert props["integration_id"] == self.integration.id
        assert props["slack_team_id"] == "T12345"
        assert props["team_id"] == self.team.id
        assert props["organization_id"] == str(self.organization.id)
        assert props["slack_user_id"] == "U1"
        assert props["foo"] == "bar"

    @patch("products.slack_app.backend.onboarding.capture_slack_event")
    @patch("products.slack_app.backend.onboarding._resolve_onboarding_user", return_value=None)
    @patch("posthog.models.integration.WebClient")
    def test_send_onboarding_dm_captures_dm_sent(self, mock_webclient_class, _resolve, mock_capture):
        client = self._client(mock_webclient_class)
        client.conversations_list.return_value = {"channels": [], "response_metadata": {"next_cursor": ""}}

        assert onboarding.send_onboarding_dm(self.integration, "U1") is True
        assert onboarding.EVENT_DM_SENT in [c.args[1] for c in mock_capture.call_args_list]

    @patch("products.slack_app.backend.onboarding.capture_slack_event")
    @patch("products.slack_app.backend.onboarding._resolve_onboarding_user", return_value=None)
    @patch("posthog.models.integration.WebClient")
    def test_apply_sources_captures_source_enabled(self, mock_webclient_class, _resolve, mock_capture):
        self._client(mock_webclient_class)
        _resolve.return_value = self.user.id

        onboarding.apply_sources_selection(self.integration, "U1", ["error_tracking"])

        assert onboarding.EVENT_SOURCE_ENABLED in [c.args[1] for c in mock_capture.call_args_list]

    @patch("products.slack_app.backend.onboarding.capture_slack_event")
    @patch("products.slack_app.backend.onboarding._onboarding_status")
    @patch("posthog.models.integration.WebClient")
    def test_maybe_complete_fires_completed_when_all_done(self, mock_webclient_class, mock_status, mock_capture):
        self._client(mock_webclient_class)
        mock_status.return_value = (7, dict.fromkeys(onboarding.OnboardingStep, True))

        onboarding._maybe_complete(self.integration, "U1")

        assert onboarding.EVENT_COMPLETED in [c.args[1] for c in mock_capture.call_args_list]

    @patch("products.slack_app.backend.onboarding.capture_slack_event")
    @patch("products.slack_app.backend.onboarding._onboarding_status")
    @patch("posthog.models.integration.WebClient")
    def test_maybe_complete_no_completed_when_remaining(self, mock_webclient_class, mock_status, mock_capture):
        self._client(mock_webclient_class)
        status = dict.fromkeys(onboarding.OnboardingStep, True)
        status[onboarding.OnboardingStep.GITHUB] = False
        mock_status.return_value = (7, status)

        onboarding._maybe_complete(self.integration, "U1")

        assert onboarding.EVENT_COMPLETED not in [c.args[1] for c in mock_capture.call_args_list]

    @patch("posthog.models.integration.WebClient")
    def test_dm_leads_with_self_driving_intro(self, mock_webclient_class):
        self._client(mock_webclient_class)

        _, blocks = onboarding.build_onboarding_dm(
            self.integration, SlackIntegration(self.integration), needs_github=True
        )

        assert blocks[0]["type"] == "section"
        assert "self-driving" in blocks[0]["text"]["text"]
        assert "first report" in self._all_text(blocks)

    @patch("products.slack_app.backend.onboarding.run_install_onboarding")
    def test_onboarding_workflow_activity_runs_for_integration(self, mock_run):
        from posthog.temporal.ai.slack_app.activities.onboarding import run_posthog_slack_inbox_onboarding

        run_posthog_slack_inbox_onboarding(self.integration.id)

        mock_run.assert_called_once()
        assert mock_run.call_args.args[0].id == self.integration.id

    @patch("products.slack_app.backend.onboarding.run_install_onboarding")
    def test_onboarding_workflow_activity_noop_for_missing_integration(self, mock_run):
        from posthog.temporal.ai.slack_app.activities.onboarding import run_posthog_slack_inbox_onboarding

        run_posthog_slack_inbox_onboarding(99999999)

        mock_run.assert_not_called()
