from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.mcp_store.backend.facade.contracts import ActiveInstallationInfo, TemplateInfo
from products.signals.backend.facade.api import ScoutProvisionResult
from products.slack_app.backend import api, persona_onboarding
from products.slack_app.backend.models import SlackSettings, SlackThreadTaskMapping
from products.tasks.backend.models import Task, TaskRun

WORKSPACE = "T1"
SLACK_USER = "U1"
DM_CHANNEL = "D1"
PICKED_CHANNEL = "C9"

FLAG = "products.slack_app.backend.persona_onboarding.is_persona_onboarding_enabled"
PROVISION = "products.signals.backend.facade.api.provision_persona_scouts"
WEBCLIENT = "posthog.models.integration.WebClient"

CSM_SKILL_NAMES = [spec.skill_name for spec in persona_onboarding.PERSONA_SCOUT_CATALOG[persona_onboarding.PERSONA_CSM]]
DIGEST_START = "products.slack_app.backend.first_patrol.start_first_patrol_digest_workflow"


def _template(name: str, *, redirect: bool = True) -> TemplateInfo:
    return TemplateInfo(
        id=f"tmpl-{name.lower()}",
        name=name,
        auth_type="oauth" if redirect else "api_key",
        icon_key="",
        connect_via_redirect=redirect,
    )


ALL_TEMPLATES = [
    _template("Salesforce"),
    _template("HubSpot"),
    _template("Zendesk"),
    _template("Intercom", redirect=False),
    _template("Linear"),
    _template("Jira"),
    _template("Stripe"),
]


@pytest.fixture(autouse=True)
def _no_temporal_digest_dispatch():
    # The completion path enqueues the first-patrol digest workflow; without this patch the
    # tests wait out a real Temporal connection attempt (~80s of timeout across the module).
    with patch(DIGEST_START) as mock_start:
        yield mock_start


@pytest.fixture(autouse=True)
def _mute_analytics():
    # Every handler fires capture_slack_event, whose ph_scoped_capture flushes on a blocking
    # network shutdown — no flow test asserts analytics, so mock it to keep the suite fast.
    with patch("products.slack_app.backend.persona_onboarding.capture_slack_event"):
        yield


class _FlowTestBase:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        cache.clear()
        self.organization = Organization.objects.create(name="Org")
        self.team = Team.objects.create(organization=self.organization, name="Team")
        self.user = User.objects.create(email="csm@example.com", first_name="Pat")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id=WORKSPACE,
            config={"scope": "chat:write,channels:manage"},
            sensitive_config={"access_token": "xoxb-test"},
        )

    def _client(self, mock_webclient_class: MagicMock) -> MagicMock:
        client = MagicMock()
        client.chat_postMessage.return_value = {"ok": True, "ts": "111.222"}
        client.chat_update.return_value = {"ok": True}
        client.conversations_open.return_value = {"channel": {"id": DM_CHANNEL}}
        client.conversations_info.return_value = {"channel": {"id": PICKED_CHANNEL, "name": "cs-alerts"}}
        client.users_info.return_value = {"user": {"profile": {"title": "", "display_name": "Pat"}}}
        client.views_publish.return_value = {"ok": True}
        mock_webclient_class.return_value = client
        return client

    def _row(self) -> SlackSettings:
        return SlackSettings.objects.get(slack_workspace_id=WORKSPACE, slack_user_id=SLACK_USER)

    def _seed_state(self, step: str, **extra: object) -> SlackSettings:
        row = persona_onboarding.get_or_create_settings_row(WORKSPACE, SLACK_USER)
        state: dict = {
            "step": step,
            "persona_candidate": None,
            "detection_source": None,
            "team_id": self.team.id,
            "integration_id": self.integration.id,
            "posthog_user_id": self.user.id,
            "dm_channel_id": DM_CHANNEL,
            "thread_ts": None,
            "kickoff_ts": "111.222",
            "started_at": "2026-07-02T00:00:00+00:00",
        }
        state.update(extra)
        row.onboarding_state = state
        row.save(update_fields=["onboarding_state", "updated_at"])
        return row

    def _payload(self, action: dict) -> dict:
        return {
            "team": {"id": WORKSPACE},
            "user": {"id": SLACK_USER},
            "channel": {"id": DM_CHANNEL},
            "message": {"ts": "1.2", "blocks": []},
            "actions": [action],
        }

    def _posted_text(self, client: MagicMock) -> str:
        parts: list[str] = []
        for call in client.chat_postMessage.call_args_list:
            parts.append(str(call.kwargs.get("text") or ""))
            for block in call.kwargs.get("blocks") or []:
                text = (block.get("text") or {}).get("text", "")
                if isinstance(text, str):
                    parts.append(text)
                for element in block.get("elements", []):
                    element_text = element.get("text")
                    parts.append(
                        element_text if isinstance(element_text, str) else (element_text or {}).get("text", "")
                    )
        return " ".join(parts)


class TestInterceptAssistantSurface(_FlowTestBase):
    def _intercept(self, entry_point: str = "first_dm") -> bool:
        return persona_onboarding.maybe_intercept_assistant_surface(
            self.integration,
            posthog_user_id=self.user.id,
            workspace_id=WORKSPACE,
            slack_user_id=SLACK_USER,
            channel_id=DM_CHANNEL,
            thread_ts=None,
            accessible_integration_ids=[self.integration.id],
            entry_point=entry_point,
        )

    @patch(FLAG, return_value=False)
    @patch(WEBCLIENT)
    def test_flag_off_is_inert(self, mock_webclient, _flag):
        client = self._client(mock_webclient)

        assert self._intercept() is False

        client.chat_postMessage.assert_not_called()
        assert not SlackSettings.objects.filter(slack_workspace_id=WORKSPACE, slack_user_id=SLACK_USER).exists()

    @patch(FLAG, return_value=True)
    @patch(WEBCLIENT)
    def test_new_user_gets_kickoff_dm_and_state(self, mock_webclient, _flag):
        client = self._client(mock_webclient)

        assert self._intercept() is True

        client.chat_postMessage.assert_called_once()
        row = self._row()
        assert row.onboarded_at is None
        state = row.onboarding_state
        assert state["step"] == persona_onboarding.STEP_AWAITING_PERSONA
        assert state["team_id"] == self.team.id
        assert state["integration_id"] == self.integration.id
        assert state["posthog_user_id"] == self.user.id

    @patch(FLAG, return_value=True)
    @patch(WEBCLIENT)
    def test_prior_activity_grandfathers_without_onboarding(self, mock_webclient, _flag):
        client = self._client(mock_webclient)
        task = Task.objects.create(team=self.team, title="t")
        task_run = TaskRun.objects.create(team=self.team, task=task)
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id=WORKSPACE,
            channel="C0",
            thread_ts="1.0",
            task=task,
            task_run=task_run,
            mentioning_slack_user_id=SLACK_USER,
            latest_actor_slack_user_id=SLACK_USER,
        )

        assert self._intercept() is False

        row = self._row()
        assert row.onboarded_at is not None
        assert row.onboarding_state is None
        client.chat_postMessage.assert_not_called()

    @patch(FLAG, return_value=True)
    @patch(WEBCLIENT)
    def test_onboarded_row_is_never_intercepted(self, mock_webclient, _flag):
        client = self._client(mock_webclient)
        row = persona_onboarding.get_or_create_settings_row(WORKSPACE, SLACK_USER)
        row.onboarded_at = timezone.now()
        row.save(update_fields=["onboarded_at", "updated_at"])

        assert self._intercept() is False

        client.chat_postMessage.assert_not_called()

    @patch(FLAG, return_value=True)
    @patch(WEBCLIENT)
    def test_dm_during_in_flight_onboarding_nudges_without_reset(self, mock_webclient, _flag):
        client = self._client(mock_webclient)
        assert self._intercept() is True
        original_kickoff_ts = self._row().onboarding_state["kickoff_ts"]
        client.chat_postMessage.reset_mock()
        client.chat_postMessage.return_value = {"ok": True, "ts": "999.999"}

        assert self._intercept(entry_point="first_dm") is True

        assert persona_onboarding.NUDGE_PERSONA_TEXT in self._posted_text(client)
        assert self._row().onboarding_state["kickoff_ts"] == original_kickoff_ts

    @patch(FLAG, return_value=True)
    @patch(WEBCLIENT)
    def test_reopened_pane_retargets_the_thread_pointer(self, mock_webclient, _flag):
        # Kickoff in the original thread, then re-open the assistant container (fresh thread):
        # the repost must land in the new thread, not the stale one.
        client = self._client(mock_webclient)
        assert self._intercept(entry_point="thread_started") is True
        persona_onboarding.maybe_intercept_assistant_surface(
            self.integration,
            posthog_user_id=self.user.id,
            workspace_id=WORKSPACE,
            slack_user_id=SLACK_USER,
            channel_id="D_NEW",
            thread_ts="new-thread-ts",
            accessible_integration_ids=[self.integration.id],
            entry_point="thread_started",
        )
        state = self._row().onboarding_state
        assert state["dm_channel_id"] == "D_NEW"
        assert state["thread_ts"] == "new-thread-ts"
        assert client.chat_postMessage.call_args.kwargs["channel"] == "D_NEW"


class TestPersonaSelection(_FlowTestBase):
    def _select(self, value: str) -> None:
        action = {"action_id": persona_onboarding.PERSONA_SELECT_ACTION_ID, "value": value}
        persona_onboarding.handle_block_action(self._payload(action), action)

    @patch(WEBCLIENT)
    def test_engineer_select_completes_onboarding(self, mock_webclient):
        client = self._client(mock_webclient)
        row = self._seed_state(persona_onboarding.STEP_AWAITING_PERSONA)

        self._select("engineer")

        row.refresh_from_db()
        assert row.persona == "engineer"
        assert row.onboarded_at is not None
        assert row.onboarding_state is None
        assert persona_onboarding.ENGINEER_COMPLETION_TEXT in self._posted_text(client)

    @patch(WEBCLIENT)
    def test_csm_select_reveals_fleet_then_asks_for_channel(self, mock_webclient):
        client = self._client(mock_webclient)
        row = self._seed_state(persona_onboarding.STEP_AWAITING_PERSONA)

        self._select("csm")

        row.refresh_from_db()
        assert row.persona == "csm"
        assert row.onboarded_at is None
        state = row.onboarding_state
        assert state["step"] == persona_onboarding.STEP_AWAITING_CHANNEL
        assert set(state["readiness"]) == {"account_pulse", "support_watch", "revenue_watch", "accounts_count"}
        assert state["detected_tools"] == []
        # The post-OAuth return leg needs this pointer to flip the reveal's ⚠️ lines to ✅.
        assert state["fleet_message_ts"] == "111.222"
        assert client.chat_postMessage.call_count == 2
        reveal_blocks, prompt_blocks = (call.kwargs["blocks"] for call in client.chat_postMessage.call_args_list)
        assert persona_onboarding.SCOUTS_DOC_URL in str(reveal_blocks)
        assert any(
            element.get("action_id") == persona_onboarding.CHANNEL_SELECT_ACTION_ID
            for block in prompt_blocks
            for element in block.get("elements", [])
        )

    @patch(WEBCLIENT)
    def test_replayed_csm_click_reposts_channel_step_without_double_transition(self, mock_webclient):
        client = self._client(mock_webclient)
        row = self._seed_state(
            persona_onboarding.STEP_AWAITING_CHANNEL,
            readiness={"account_pulse": False, "support_watch": False, "revenue_watch": False, "accounts_count": 0},
            detected_tools=[],
        )
        row.persona = persona_onboarding.PERSONA_CSM
        row.save(update_fields=["persona"])

        self._select("csm")

        row.refresh_from_db()
        assert row.onboarded_at is None
        assert row.onboarding_state["step"] == persona_onboarding.STEP_AWAITING_CHANNEL
        assert client.chat_postMessage.call_count == 1
        assert persona_onboarding.SCOUTS_DOC_URL not in self._posted_text(client)
        assert any(
            element.get("action_id") == persona_onboarding.CHANNEL_SELECT_ACTION_ID
            for block in client.chat_postMessage.call_args.kwargs["blocks"]
            for element in block.get("elements", [])
        )

    @parameterized.expand(
        [
            ("top_level_click", {"ts": "555.1", "blocks": []}, "555.1"),
            ("threaded_click", {"ts": "555.2", "thread_ts": "555.1", "blocks": []}, "555.1"),
        ]
    )
    @patch(WEBCLIENT)
    def test_reply_threads_under_clicked_message(self, _name, message, expected_anchor, mock_webclient):
        # A reply outside the clicked message's thread opens a brand-new conversation in the
        # assistant surface — the click location must win over the stored (here: None) pointer.
        client = self._client(mock_webclient)
        self._seed_state(persona_onboarding.STEP_AWAITING_PERSONA)
        action = {"action_id": persona_onboarding.PERSONA_SELECT_ACTION_ID, "value": "engineer"}
        payload = self._payload(action)
        payload["message"] = message

        persona_onboarding.handle_block_action(payload, action)

        assert client.chat_postMessage.call_count >= 1
        assert all(call.kwargs["thread_ts"] == expected_anchor for call in client.chat_postMessage.call_args_list)

    @patch(WEBCLIENT)
    def test_skip_marks_onboarded_without_persona(self, mock_webclient):
        client = self._client(mock_webclient)
        row = self._seed_state(persona_onboarding.STEP_AWAITING_PERSONA)
        action = {"action_id": persona_onboarding.SKIP_ACTION_ID}

        persona_onboarding.handle_block_action(self._payload(action), action)

        row.refresh_from_db()
        assert row.onboarded_at is not None
        assert row.persona is None
        assert row.onboarding_state is None
        assert persona_onboarding.SKIP_TEXT in self._posted_text(client)


class TestChannelStep(_FlowTestBase):
    def _seed_channel_state(self) -> SlackSettings:
        row = self._seed_state(
            persona_onboarding.STEP_AWAITING_CHANNEL,
            readiness={"account_pulse": False, "support_watch": False, "revenue_watch": False, "accounts_count": 0},
            detected_tools=[],
        )
        row.persona = persona_onboarding.PERSONA_CSM
        row.save(update_fields=["persona"])
        return row

    def _results(self, channel_conflict: str | None = None) -> list[ScoutProvisionResult]:
        return [
            ScoutProvisionResult(
                skill_name=skill_name,
                config_id=f"cfg-{index}",
                created=True,
                channel_conflict=channel_conflict if index == 0 else None,
                first_run_started=True,
            )
            for index, skill_name in enumerate(CSM_SKILL_NAMES)
        ]

    def _select_channel(self) -> None:
        action = {"action_id": persona_onboarding.CHANNEL_SELECT_ACTION_ID, "selected_conversation": PICKED_CHANNEL}
        persona_onboarding.handle_block_action(self._payload(action), action)

    @patch(PROVISION)
    @patch(WEBCLIENT)
    def test_channel_select_provisions_fleet_and_finalizes_row(self, mock_webclient, mock_provision):
        client = self._client(mock_webclient)
        mock_provision.return_value = self._results()
        row = self._seed_channel_state()

        self._select_channel()

        mock_provision.assert_called_once()
        kwargs = mock_provision.call_args.kwargs
        assert kwargs["team"] == self.team
        assert kwargs["created_by"] == self.user
        assert kwargs["slack_integration_id"] == self.integration.id
        assert kwargs["channel_id"] == PICKED_CHANNEL
        assert kwargs["channel_name"] == "cs-alerts"
        assert kwargs["skill_names"] == CSM_SKILL_NAMES
        row.refresh_from_db()
        assert row.persona == persona_onboarding.PERSONA_CSM
        assert row.onboarded_at is not None
        assert row.onboarding_state is None
        assert "locked in" in self._posted_text(client)

    @patch(PROVISION)
    @patch(WEBCLIENT)
    def test_skip_at_channel_step_onboards_without_provisioning(self, mock_webclient, mock_provision):
        # A CSM who can't/won't pick a channel must be able to bail — otherwise the DM intercept
        # wedges them out of the assistant entirely.
        client = self._client(mock_webclient)
        row = self._seed_channel_state()
        action = {"action_id": persona_onboarding.SKIP_ACTION_ID}
        persona_onboarding.handle_block_action(self._payload(action), action)
        mock_provision.assert_not_called()
        row.refresh_from_db()
        assert row.onboarded_at is not None
        assert row.onboarding_state is None
        assert "skipping setup" in self._posted_text(client).lower()

    @patch(PROVISION)
    @patch(WEBCLIENT)
    def test_channel_prompt_and_invite_offer_a_skip(self, mock_webclient, mock_provision):
        assert any(
            element.get("action_id") == persona_onboarding.SKIP_ACTION_ID
            for block in persona_onboarding.build_channel_prompt_blocks(True)
            for element in block.get("elements", [])
        )
        assert any(
            element.get("action_id") == persona_onboarding.SKIP_ACTION_ID
            for block in persona_onboarding.build_invite_needed_blocks("C1", "alerts")
            for element in block.get("elements", [])
        )

    @patch(PROVISION)
    @patch(WEBCLIENT)
    def test_provisioning_failure_leaves_user_unonboarded_and_retryable(self, mock_webclient, mock_provision):
        client = self._client(mock_webclient)
        mock_provision.side_effect = RuntimeError("temporal down")
        row = self._seed_channel_state()
        self._select_channel()
        row.refresh_from_db()
        assert row.onboarded_at is None
        assert row.onboarding_state["step"] == persona_onboarding.STEP_AWAITING_CHANNEL
        assert "something went wrong" in self._posted_text(client).lower()

    @patch(PROVISION)
    @patch(WEBCLIENT)
    def test_not_in_channel_defers_provisioning_until_verify(self, mock_webclient, mock_provision):
        client = self._client(mock_webclient)
        mock_provision.return_value = self._results()
        row = self._seed_channel_state()

        def reject_picked_channel(channel=None, **kwargs):
            if channel == PICKED_CHANNEL:
                raise SlackApiError("not_in_channel", {"error": "not_in_channel"})
            return {"ok": True, "ts": "1.3"}

        client.chat_postMessage.side_effect = reject_picked_channel
        self._select_channel()

        mock_provision.assert_not_called()
        row.refresh_from_db()
        assert row.onboarded_at is None
        assert row.onboarding_state["pending_channel_id"] == PICKED_CHANNEL
        assert "/invite" in self._posted_text(client)

        client.chat_postMessage.side_effect = None
        verify_action = {"action_id": persona_onboarding.CHANNEL_VERIFY_ACTION_ID, "value": PICKED_CHANNEL}
        with patch.object(persona_onboarding, "capture_slack_event") as capture:
            persona_onboarding.handle_block_action(self._payload(verify_action), verify_action)

        mock_provision.assert_called_once()
        assert mock_provision.call_args.kwargs["channel_id"] == PICKED_CHANNEL
        # The /invite-then-verify path must carry its own funnel label so it stays distinct from
        # the dropdown path in the channel-configured conversion.
        configured = [c for c in capture.call_args_list if c.args[1] == persona_onboarding.EVENT_CHANNEL_CONFIGURED]
        assert [c.kwargs["method"] for c in configured] == ["verified"]
        row.refresh_from_db()
        assert row.onboarded_at is not None
        assert row.onboarding_state is None

    @patch(PROVISION, side_effect=RuntimeError("enabled cap reached"))
    @patch(WEBCLIENT)
    def test_provisioning_failure_keeps_flow_retryable(self, mock_webclient, _mock_provision):
        client = self._client(mock_webclient)
        row = self._seed_channel_state()

        self._select_channel()

        row.refresh_from_db()
        assert row.onboarded_at is None
        assert row.onboarding_state["step"] == persona_onboarding.STEP_AWAITING_CHANNEL
        assert persona_onboarding.ERROR_TEXT in self._posted_text(client)

    @patch(PROVISION)
    @patch(WEBCLIENT)
    def test_channel_conflict_uses_already_running_copy(self, mock_webclient, mock_provision):
        client = self._client(mock_webclient)
        mock_provision.return_value = self._results(channel_conflict="scout-hq")
        row = self._seed_channel_state()

        self._select_channel()

        text = self._posted_text(client)
        assert "already running" in text
        assert "#scout-hq" in text
        row.refresh_from_db()
        assert row.onboarded_at is not None


class TestHomeOnboardingStatus(_FlowTestBase):
    @parameterized.expand(
        [
            ("flag_off", False, "in_flight", "hidden"),
            ("no_row", True, None, "start"),
            ("in_flight", True, "in_flight", "in_progress"),
            ("onboarded", True, "onboarded", "hidden"),
        ]
    )
    @patch(FLAG)
    def test_home_card_status_matrix(self, _name, flag_on, row_state, expected, mock_flag):
        mock_flag.return_value = flag_on
        if row_state == "in_flight":
            self._seed_state(persona_onboarding.STEP_AWAITING_PERSONA)
        elif row_state == "onboarded":
            row = persona_onboarding.get_or_create_settings_row(WORKSPACE, SLACK_USER)
            row.onboarded_at = timezone.now()
            row.save(update_fields=["onboarded_at", "updated_at"])

        assert persona_onboarding.compute_home_onboarding_status(self.integration, WORKSPACE, SLACK_USER) == expected


class TestPersonaOnboardingInteractivityRouting:
    @parameterized.expand(
        [
            ("persona_step_action", "block_actions", persona_onboarding.PERSONA_SELECT_ACTION_ID, True),
            ("home_start_action", "block_actions", persona_onboarding.START_ACTION_ID, True),
            ("unrelated_action", "block_actions", "posthog_code_repo_select", False),
            ("view_submission", "view_submission", persona_onboarding.PERSONA_SELECT_ACTION_ID, False),
        ]
    )
    def test_is_persona_onboarding_interactivity(self, _name, payload_type, action_id, expected):
        payload = {"actions": [{"action_id": action_id}]}
        assert api._is_persona_onboarding_interactivity(payload, payload_type) is expected

    def test_payload_without_actions_is_not_claimed(self):
        assert api._is_persona_onboarding_interactivity({}, "block_actions") is False


class TestBlockKitActionIdUniqueness:
    # Slack rejects any message whose interactive elements share an action_id (`invalid_blocks`),
    # so every builder that can emit sibling buttons is exercised in its busiest configuration.
    @parameterized.expand(
        [
            ("kickoff_ask", lambda: persona_onboarding.build_kickoff_blocks("Pat", None)),
            (
                "kickoff_csm_candidate",
                lambda: persona_onboarding.build_kickoff_blocks("Pat", persona_onboarding.PERSONA_CSM),
            ),
            (
                "kickoff_engineer_candidate",
                lambda: persona_onboarding.build_kickoff_blocks("Pat", persona_onboarding.PERSONA_ENGINEER),
            ),
            (
                "fleet_reveal_all_gaps_no_templates",
                lambda: persona_onboarding.build_fleet_reveal_blocks(1, {}, [], [], "T1", "U1"),
            ),
            (
                "fleet_reveal_all_gaps_templates_and_tools",
                lambda: persona_onboarding.build_fleet_reveal_blocks(
                    1, {}, ["Linear", "Zendesk"], ALL_TEMPLATES, "T1", "U1"
                ),
            ),
            ("channel_prompt_with_create", lambda: persona_onboarding.build_channel_prompt_blocks(True)),
            ("invite_needed", lambda: persona_onboarding.build_invite_needed_blocks("C1", "posthog-inbox")),
        ]
    )
    def test_action_ids_unique_within_message(self, _name, build):
        blocks = build()
        action_ids = [
            element["action_id"]
            for block in blocks
            for element in block.get("elements", [])
            if isinstance(element, dict) and "action_id" in element
        ]
        assert action_ids, "builder emitted no interactive elements — extractor or builder is broken"
        assert len(action_ids) == len(set(action_ids)), f"duplicate action_ids in one message: {action_ids}"


class TestFleetRevealConnectButtons:
    def _buttons_by_label(self, blocks: list[dict]) -> dict[str, dict]:
        return {
            element["text"]["text"]: element
            for block in blocks
            for element in block.get("elements", [])
            if isinstance(element, dict) and element.get("type") == "button"
        }

    def test_connect_buttons_link_into_mcp_connect_flow(self):
        blocks = persona_onboarding.build_fleet_reveal_blocks(1, {}, ["Zendesk"], ALL_TEMPLATES, WORKSPACE, SLACK_USER)
        buttons = self._buttons_by_label(blocks)

        zendesk = buttons["Connect Zendesk"]
        assert "/integrations/connect-mcp/tmpl-zendesk/" in zendesk["url"]
        query = parse_qs(urlparse(zendesk["url"]).query)
        assert query["project_id"] == ["1"]
        payload = persona_onboarding.unsign_connect_state(query["state"][0])
        assert payload == {"w": WORKSPACE, "u": SLACK_USER, "k": "support_watch", "t": "Zendesk"}

        # API-key templates can't finish from a bare redirect — their button deep-links to the store.
        intercom = buttons["Connect Intercom"]
        assert "/settings/mcp-servers?mcp=tmpl-intercom" in intercom["url"]

    def test_without_matching_templates_offers_store_browse(self):
        blocks = persona_onboarding.build_fleet_reveal_blocks(1, {}, [], [], WORKSPACE, SLACK_USER)
        buttons = [
            element
            for block in blocks
            for element in block.get("elements", [])
            if isinstance(element, dict) and element.get("type") == "button"
        ]
        assert len(buttons) == len(persona_onboarding.PERSONA_SCOUT_CATALOG[persona_onboarding.PERSONA_CSM])
        assert all(button["text"]["text"] == "Browse the MCP store" for button in buttons)
        assert all("/settings/mcp-servers" in button["url"] for button in buttons)


class TestCsmReadinessWithMcpInstallations(_FlowTestBase):
    @parameterized.expand(
        [
            ("crm_feeds_account_pulse", "HubSpot", "account_pulse"),
            ("ticketing_feeds_support_watch", "Jira", "support_watch"),
            ("billing_feeds_revenue_watch", "Stripe", "revenue_watch"),
        ]
    )
    def test_connected_server_marks_only_its_scout_ready(self, _name, server_name, readiness_key):
        installation = ActiveInstallationInfo(id="i1", name="My server", proxy_path="/x", template_name=server_name)
        with patch.object(persona_onboarding, "get_active_installations", return_value=[installation]):
            readiness = persona_onboarding.check_csm_data_readiness(self.team.id, self.user.id)
        assert getattr(readiness, readiness_key) is True
        others = {"account_pulse", "support_watch", "revenue_watch"} - {readiness_key}
        assert not any(getattr(readiness, key) for key in others)


class TestMcpConnectReturn(_FlowTestBase):
    URL = "/integrations/slack/mcp-connected/"

    def _signed_state(self) -> str:
        return persona_onboarding.sign_connect_state(WORKSPACE, SLACK_USER, "revenue_watch", "Stripe")

    def _seed_channel_step(self, **extra: object) -> SlackSettings:
        return self._seed_state(
            persona_onboarding.STEP_AWAITING_CHANNEL,
            readiness={"account_pulse": False, "support_watch": False, "revenue_watch": False, "accounts_count": 0},
            detected_tools=[],
            fleet_message_ts="42.42",
            **extra,
        )

    @patch(WEBCLIENT)
    def test_success_updates_fleet_message_and_links_back_to_slack(self, mock_webclient):
        client = self._client(mock_webclient)
        self._seed_channel_step()
        stripe = ActiveInstallationInfo(id="i1", name="Stripe", proxy_path="/x", template_name="Stripe")
        with (
            patch.object(persona_onboarding, "get_active_installations", return_value=[stripe]),
            patch.object(persona_onboarding, "list_active_templates", return_value=ALL_TEMPLATES),
        ):
            response = Client().get(self.URL, {"state": self._signed_state(), "status": "success"})

        assert response.status_code == 200
        assert f"slack://channel?team={WORKSPACE}&amp;id={DM_CHANNEL}" in response.content.decode()
        client.chat_update.assert_called_once()
        assert client.chat_update.call_args.kwargs["ts"] == "42.42"
        assert self._row().onboarding_state["readiness"]["revenue_watch"] is True

    @patch(WEBCLIENT)
    def test_replayed_return_captures_connect_event_once(self, mock_webclient):
        # The signed state is reusable for 30 days; a back-button/reload must not re-fire the
        # connect-conversion event, while the fleet refresh (DB-recomputed) still runs each time.
        client = self._client(mock_webclient)
        self._seed_channel_step()
        stripe = ActiveInstallationInfo(id="i1", name="Stripe", proxy_path="/x", template_name="Stripe")
        state = self._signed_state()
        with (
            patch.object(persona_onboarding, "get_active_installations", return_value=[stripe]),
            patch.object(persona_onboarding, "list_active_templates", return_value=ALL_TEMPLATES),
            patch.object(persona_onboarding, "capture_slack_event") as capture,
        ):
            first = Client().get(self.URL, {"state": state, "status": "success"})
            second = Client().get(self.URL, {"state": state, "status": "success"})

        assert first.status_code == 200
        assert second.status_code == 200
        capture.assert_called_once()
        assert capture.call_args.args[1] == persona_onboarding.EVENT_MCP_CONNECTED
        assert client.chat_update.call_count == 2

    @patch(WEBCLIENT)
    def test_error_status_skips_message_update(self, mock_webclient):
        client = self._client(mock_webclient)
        self._seed_channel_step()

        response = Client().get(self.URL, {"state": self._signed_state(), "status": "error", "error": "cancelled"})

        assert response.status_code == 200
        client.chat_update.assert_not_called()

    def test_invalid_state_rejected(self):
        assert Client().get(self.URL, {"state": "garbage"}).status_code == 400


class TestHomeStartFlow(_FlowTestBase):
    # The Start button must ack inside Slack's 3s budget, so the kickoff work runs in a
    # background task; this pins the wiring end to end — click → kickoff DM posted, state row
    # created, home republished — with the background seam collapsed to inline.
    @patch(WEBCLIENT)
    def test_click_posts_kickoff_and_republishes_home(self, mock_webclient_class):
        client = self._client(mock_webclient_class)
        workspace_result = MagicMock(candidates=[self.integration], integration=self.integration)
        user_resolution = MagicMock(user=self.user, integration=self.integration, candidates=[self.integration])
        action = {"action_id": persona_onboarding.START_ACTION_ID}
        with (
            patch(FLAG, return_value=True),
            patch.object(persona_onboarding, "_run_in_background", side_effect=lambda fn, task: fn()),
            patch.object(persona_onboarding, "load_integrations", return_value=workspace_result),
            patch.object(persona_onboarding, "resolve_user_for_workspace", return_value=user_resolution),
            patch.object(persona_onboarding, "_republish_home") as republish,
        ):
            response = persona_onboarding.handle_block_action(
                {"team": {"id": WORKSPACE}, "user": {"id": SLACK_USER}, "actions": [action]}, action
            )
        assert response.status_code == 200
        client.chat_postMessage.assert_called_once()
        row = self._row()
        assert row.onboarding_state["step"] == persona_onboarding.STEP_AWAITING_PERSONA
        # Follow-ups must thread under the kickoff — an unthreaded reply roots a brand-new
        # conversation in the assistant surface instead of continuing this one.
        assert row.onboarding_state["thread_ts"] == "111.222"
        republish.assert_called_once()
