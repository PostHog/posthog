"""Tests for the App Home tab + AI preferences modal.

Combines the pure renderer tests (Block Kit dict shapes) with the end-to-end
handler tests (real Django flow, Slack client mocked). One shared autouse
fixture stubs the tasks-facade + LLM-gateway-models modules so the test env's
`SANDBOX_PROVIDER=docker` + `DEBUG=False` combination doesn't trigger an
eager docker-sandbox load on import.
"""

from __future__ import annotations

import sys
import json
from dataclasses import dataclass
from types import ModuleType

import pytest
from unittest.mock import MagicMock, patch

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.models import SlackSettings
from products.slack_app.backend.services.slack_app_home import (
    ACTION_EDIT_PERSONAL,
    ACTION_EDIT_WORKSPACE,
    ACTION_RESET_PERSONAL,
    ACTION_RESET_PROJECT_PERSONAL,
    EDIT_MODAL_PERSONAL_CALLBACK_ID,
    EDIT_MODAL_WORKSPACE_CALLBACK_ID,
    MODAL_ACTION_MODEL,
    MODAL_ACTION_REASONING_EFFORT,
    MODAL_ACTION_RUNTIME_ADAPTER,
    MODAL_BLOCK_MODEL,
    MODAL_BLOCK_REASONING_EFFORT,
    MODAL_BLOCK_RUNTIME_ADAPTER,
    PreferenceSource,
    handle_ai_preferences_block_action,
    handle_app_home_opened,
    handle_app_home_view_submission,
    parse_modal_submission,
    render_edit_modal,
    render_home_view,
    resolve_source,
)
from products.slack_app.backend.services.slack_settings import AIPreferences

SLACK_WORKSPACE_ID = "T_HOME"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def slack_integration(db):
    organization = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=organization, name="Team")
    return Integration.objects.create(
        team=team,
        kind="slack",
        integration_id=SLACK_WORKSPACE_ID,
        sensitive_config={"access_token": "xoxb"},
    )


@pytest.fixture
def mock_slack_client():
    fake_client = MagicMock()
    with patch("products.slack_app.backend.services.slack_app_home.SlackIntegration") as cls:
        instance = MagicMock()
        instance.client = fake_client
        cls.return_value = instance
        yield fake_client


@pytest.fixture
def flag_on():
    with patch(
        "products.slack_app.backend.feature_flags.posthoganalytics.feature_enabled",
        return_value=True,
    ):
        yield


@pytest.fixture
def admin_user():
    with patch(
        "products.slack_app.backend.services.slack_app_home.is_slack_workspace_admin",
        return_value=True,
    ):
        yield


@pytest.fixture
def non_admin_user():
    with patch(
        "products.slack_app.backend.services.slack_app_home.is_slack_workspace_admin",
        return_value=False,
    ):
        yield


@pytest.fixture(autouse=True)
def _stub_picker_facade():
    """Stub `tasks.facade.run_config` and the LLM-gateway model fetch.

    The tasks facade pulls in `tasks.temporal` on import, which the test env
    can't satisfy. The gateway fetch would hit a real network. Both get
    replaced with deterministic in-memory fakes covering every model the
    renderer and handler tests reference.
    """

    class _Effort:
        def __init__(self, value):
            self.value = value

    class _Adapter:
        def __init__(self, value):
            self.value = value

    class _RuntimeAdapter:
        CLAUDE = _Adapter("claude")
        CODEX = _Adapter("codex")

        def __iter__(self):
            return iter([self.CLAUDE, self.CODEX])

    supported_by_model = {
        ("claude", "claude-opus-4-7"): ("low", "medium", "high", "xhigh", "max"),
        ("claude", "claude-sonnet-4-6"): ("low", "medium", "high"),
        ("codex", "gpt-5"): ("low", "medium", "high"),
        ("codex", "gpt-5.5"): ("low", "medium", "high", "xhigh"),
    }
    public_efforts = tuple(_Effort(v) for v in ("low", "medium", "high", "xhigh", "max"))

    def fake_get_supported(adapter, model):
        adapter_value = adapter.value if hasattr(adapter, "value") else adapter
        return tuple(_Effort(v) for v in supported_by_model.get((adapter_value, model), ()))

    def fake_get_error(adapter, model, effort):
        if adapter is None or model is None or effort is None:
            return None
        if effort in supported_by_model.get((adapter, model), ()):
            return None
        return f"Effort '{effort}' not supported on {model}."

    facade_name = "products.tasks.backend.facade.run_config"
    fake = ModuleType(facade_name)
    fake.RuntimeAdapter = _RuntimeAdapter()
    fake.get_supported_reasoning_efforts = fake_get_supported
    fake.get_reasoning_effort_error = fake_get_error
    fake.PUBLIC_REASONING_EFFORTS = public_efforts

    @dataclass(frozen=True)
    class _GatewayModel:
        id: str
        owned_by: str
        context_window: int = 200_000

    gateway_models = (
        _GatewayModel(id="claude-opus-4-7", owned_by="anthropic"),
        _GatewayModel(id="claude-sonnet-4-6", owned_by="anthropic"),
        _GatewayModel(id="gpt-5", owned_by="openai"),
        _GatewayModel(id="gpt-5.5", owned_by="openai"),
    )
    llm_models_name = "products.slack_app.backend.services.llm_models"
    fake_llm_models = ModuleType(llm_models_name)
    fake_llm_models.list_slack_app_models = lambda: gateway_models
    fake_llm_models.GatewayModel = _GatewayModel

    saved_facade = sys.modules.get(facade_name)
    saved_llm = sys.modules.get(llm_models_name)
    sys.modules[facade_name] = fake
    sys.modules[llm_models_name] = fake_llm_models
    try:
        yield
    finally:
        if saved_facade is None:
            sys.modules.pop(facade_name, None)
        else:
            sys.modules[facade_name] = saved_facade
        if saved_llm is None:
            sys.modules.pop(llm_models_name, None)
        else:
            sys.modules[llm_models_name] = saved_llm


# ---------------------------------------------------------------------------
# Renderer helpers
# ---------------------------------------------------------------------------


def _make_row(*, runtime_adapter=None, model=None, reasoning_effort=None):
    """Plain duck-type stand-in for a SlackSettings row — keeps the renderer
    tests off the database."""

    class _Row:
        pass

    row = _Row()
    row.runtime_adapter = runtime_adapter
    row.model = model
    row.reasoning_effort = reasoning_effort
    return row


def _action_ids(view: dict) -> list[str]:
    out: list[str] = []
    for block in view["blocks"]:
        for el in block.get("elements", []) or []:
            if "action_id" in el:
                out.append(el["action_id"])
    return out


def _block_ids(view: dict) -> list[str]:
    return [b.get("block_id") for b in view["blocks"] if b.get("block_id")]


def _all_text(view: dict) -> str:
    """Flatten all `text` fields for substring assertions."""
    out: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if "text" in node and isinstance(node["text"], str):
                out.append(node["text"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(view)
    return " ".join(out)


def _build_submission(*, runtime_adapter=None, model=None, effort=None) -> dict:
    state: dict = {}
    if runtime_adapter:
        state[MODAL_BLOCK_RUNTIME_ADAPTER] = {
            MODAL_ACTION_RUNTIME_ADAPTER: {"selected_option": {"value": runtime_adapter}}
        }
    if model:
        state[MODAL_BLOCK_MODEL] = {MODAL_ACTION_MODEL: {"selected_option": {"value": model}}}
    if effort:
        state[MODAL_BLOCK_REASONING_EFFORT] = {MODAL_ACTION_REASONING_EFFORT: {"selected_option": {"value": effort}}}
    return {"state": {"values": state}}


# ---------------------------------------------------------------------------
# Handler helpers
# ---------------------------------------------------------------------------


def _block_action_payload(
    *,
    action_id: str,
    slack_user_id: str,
    trigger_id: str | None = None,
    channel: str | None = None,
) -> dict:
    return {
        "type": "block_actions",
        "team": {"id": SLACK_WORKSPACE_ID},
        "user": {"id": slack_user_id},
        "trigger_id": trigger_id,
        "channel": {"id": channel} if channel else None,
        "actions": [{"action_id": action_id}],
    }


def _view_submission_payload(
    *,
    callback_id: str,
    slack_user_id: str,
    runtime_adapter: str | None,
    model: str | None,
    effort: str | None,
) -> dict:
    state: dict = {}
    if runtime_adapter:
        state[MODAL_BLOCK_RUNTIME_ADAPTER] = {
            MODAL_ACTION_RUNTIME_ADAPTER: {"selected_option": {"value": runtime_adapter}}
        }
    if model:
        state[MODAL_BLOCK_MODEL] = {MODAL_ACTION_MODEL: {"selected_option": {"value": model}}}
    if effort:
        state[MODAL_BLOCK_REASONING_EFFORT] = {"ai_prefs:reasoning_effort": {"selected_option": {"value": effort}}}
    return {
        "type": "view_submission",
        "team": {"id": SLACK_WORKSPACE_ID},
        "user": {"id": slack_user_id},
        "view": {
            "id": "V1",
            "hash": "H1",
            "callback_id": callback_id,
            "state": {"values": state},
        },
    }


# ---------------------------------------------------------------------------
# Renderer tests
# ---------------------------------------------------------------------------


class TestRenderHomeView:
    def test_empty_state_renders_buttons_and_no_reset(self):
        view = render_home_view(
            effective=AIPreferences(),
            user_row=None,
            workspace_row=None,
            is_admin=False,
        )
        assert view["type"] == "home"
        ids = _action_ids(view)
        # Personal edit always present; reset hidden when no override; non-admin
        # doesn't see the workspace edit button.
        assert ACTION_EDIT_PERSONAL in ids
        assert ACTION_RESET_PERSONAL not in ids
        assert ACTION_EDIT_WORKSPACE not in ids

    def test_admin_sees_workspace_edit_button(self):
        view = render_home_view(
            effective=AIPreferences(),
            user_row=None,
            workspace_row=None,
            is_admin=True,
        )
        assert ACTION_EDIT_WORKSPACE in _action_ids(view)

    def test_personal_override_renders_reset_button(self):
        view = render_home_view(
            effective=AIPreferences(runtime_adapter="claude", model="claude-opus-4-7", reasoning_effort="high"),
            user_row=_make_row(runtime_adapter="claude", model="claude-opus-4-7", reasoning_effort="high"),
            workspace_row=None,
            is_admin=False,
        )
        assert ACTION_RESET_PERSONAL in _action_ids(view)

    def test_active_model_summary_mentions_model_label(self):
        view = render_home_view(
            effective=AIPreferences(runtime_adapter="claude", model="claude-opus-4-7", reasoning_effort="high"),
            user_row=None,
            workspace_row=_make_row(runtime_adapter="claude", model="claude-opus-4-7", reasoning_effort="high"),
            is_admin=True,
        )
        text_blob = " ".join(block["text"]["text"] for block in view["blocks"] if block.get("type") == "section")
        # Friendly label rather than raw model id; source attribution visible.
        assert "Claude Opus 4.7" in text_blob
        assert "Workspace default" in _all_text(view)

    def test_source_resolution_is_atomic(self):
        # User has only `reasoning_effort` set (no pair). Source should fall
        # through to the workspace's complete pair.
        assert (
            resolve_source(
                _make_row(reasoning_effort="medium"),
                _make_row(runtime_adapter="claude", model="claude-opus-4-7"),
            )
            == PreferenceSource.workspace()
        )

    def test_source_unset_when_neither_row_has_pair(self):
        assert resolve_source(None, None) == PreferenceSource.unset()
        assert resolve_source(_make_row(reasoning_effort="high"), None) == PreferenceSource.unset()


class TestRenderEditModal:
    @pytest.mark.parametrize(
        "scope,callback_id",
        [
            ("personal", EDIT_MODAL_PERSONAL_CALLBACK_ID),
            ("workspace", EDIT_MODAL_WORKSPACE_CALLBACK_ID),
        ],
    )
    def test_callback_id_matches_scope(self, scope, callback_id):
        view = render_edit_modal(scope=scope, current=AIPreferences())
        assert view["callback_id"] == callback_id

    def test_no_runtime_means_no_model_or_effort_blocks(self):
        view = render_edit_modal(scope="personal", current=AIPreferences())
        ids = _block_ids(view)
        assert MODAL_BLOCK_RUNTIME_ADAPTER in ids
        assert MODAL_BLOCK_MODEL not in ids
        assert MODAL_BLOCK_REASONING_EFFORT not in ids

    def test_runtime_picked_unlocks_model_block(self):
        view = render_edit_modal(scope="personal", current=AIPreferences(runtime_adapter="claude"))
        ids = _block_ids(view)
        assert MODAL_BLOCK_MODEL in ids
        # Effort block needs both the model and a non-empty supported list.
        assert MODAL_BLOCK_REASONING_EFFORT not in ids

    def test_model_options_match_runtime(self):
        view = render_edit_modal(scope="personal", current=AIPreferences(runtime_adapter="codex"))
        model_block = next(b for b in view["blocks"] if b.get("block_id") == MODAL_BLOCK_MODEL)
        option_values = [o["value"] for o in model_block["element"]["options"]]
        # Codex models only — assert via prefix to stay resilient as the facade
        # adds new Codex ids.
        assert option_values
        assert all(v.startswith("gpt-") for v in option_values)

    def test_effort_block_renders_only_when_supported_efforts_provided(self):
        view = render_edit_modal(
            scope="personal",
            current=AIPreferences(runtime_adapter="claude", model="claude-opus-4-7"),
            supported_efforts=["low", "medium", "high"],
        )
        block = next(b for b in view["blocks"] if b.get("block_id") == MODAL_BLOCK_REASONING_EFFORT)
        assert block["optional"] is True
        values = [o["value"] for o in block["element"]["options"]]
        assert values == ["low", "medium", "high"]

    def test_initial_options_reflect_current_values(self):
        view = render_edit_modal(
            scope="workspace",
            current=AIPreferences(
                runtime_adapter="claude",
                model="claude-opus-4-7",
                reasoning_effort="high",
            ),
            supported_efforts=["low", "medium", "high"],
        )
        runtime_block = next(b for b in view["blocks"] if b.get("block_id") == MODAL_BLOCK_RUNTIME_ADAPTER)
        model_block = next(b for b in view["blocks"] if b.get("block_id") == MODAL_BLOCK_MODEL)
        effort_block = next(b for b in view["blocks"] if b.get("block_id") == MODAL_BLOCK_REASONING_EFFORT)
        assert runtime_block["element"]["initial_option"]["value"] == "claude"
        assert model_block["element"]["initial_option"]["value"] == "claude-opus-4-7"
        assert effort_block["element"]["initial_option"]["value"] == "high"

    def test_dispatch_action_set_on_runtime_and_model(self):
        view = render_edit_modal(scope="personal", current=AIPreferences(runtime_adapter="claude"))
        runtime_block = next(b for b in view["blocks"] if b.get("block_id") == MODAL_BLOCK_RUNTIME_ADAPTER)
        model_block = next(b for b in view["blocks"] if b.get("block_id") == MODAL_BLOCK_MODEL)
        # dispatch_action triggers a block_actions payload so the modal can
        # re-render with downstream options matching the new selection.
        assert runtime_block["dispatch_action"] is True
        assert model_block["dispatch_action"] is True


class TestParseModalSubmission:
    def test_all_three_picked(self):
        view = _build_submission(runtime_adapter="claude", model="claude-opus-4-7", effort="high")
        assert parse_modal_submission(view) == ("claude", "claude-opus-4-7", "high")

    def test_no_state_returns_all_none(self):
        assert parse_modal_submission({}) == (None, None, None)

    def test_partial_state_returns_partial_tuple(self):
        view = _build_submission(runtime_adapter="claude")
        assert parse_modal_submission(view) == ("claude", None, None)


# ---------------------------------------------------------------------------
# Handler tests — app_home_opened event
# ---------------------------------------------------------------------------


class TestHandleAppHomeOpened:
    def test_publishes_view_for_known_user(self, slack_integration, mock_slack_client, flag_on, admin_user):
        handle_app_home_opened({"user": "U001"}, SLACK_WORKSPACE_ID)
        assert mock_slack_client.views_publish.called
        kwargs = mock_slack_client.views_publish.call_args.kwargs
        assert kwargs["user_id"] == "U001"
        assert kwargs["view"]["type"] == "home"

    def test_noop_when_user_missing(self, slack_integration, mock_slack_client, flag_on):
        handle_app_home_opened({}, SLACK_WORKSPACE_ID)
        assert not mock_slack_client.views_publish.called

    def test_noop_when_integration_missing(self, db, mock_slack_client, flag_on):
        handle_app_home_opened({"user": "U001"}, "T_UNKNOWN")
        assert not mock_slack_client.views_publish.called


# ---------------------------------------------------------------------------
# Handler tests — block_actions
# ---------------------------------------------------------------------------


class TestEditPersonalAction:
    def test_opens_modal(self, slack_integration, mock_slack_client, flag_on, admin_user):
        payload = _block_action_payload(
            action_id=ACTION_EDIT_PERSONAL,
            slack_user_id="U001",
            trigger_id="trig.1",
        )
        handle_ai_preferences_block_action(payload, payload["actions"][0])
        assert mock_slack_client.views_open.called
        view = mock_slack_client.views_open.call_args.kwargs["view"]
        assert view["callback_id"] == EDIT_MODAL_PERSONAL_CALLBACK_ID


class TestEditWorkspaceAdminGate:
    def test_admin_opens_modal(self, slack_integration, mock_slack_client, flag_on, admin_user):
        payload = _block_action_payload(
            action_id=ACTION_EDIT_WORKSPACE,
            slack_user_id="U001",
            trigger_id="trig.2",
        )
        handle_ai_preferences_block_action(payload, payload["actions"][0])
        assert mock_slack_client.views_open.called

    def test_non_admin_blocked(self, slack_integration, mock_slack_client, flag_on, non_admin_user):
        payload = _block_action_payload(
            action_id=ACTION_EDIT_WORKSPACE,
            slack_user_id="U001",
            trigger_id="trig.3",
            channel="C1",
        )
        handle_ai_preferences_block_action(payload, payload["actions"][0])
        # Non-admin gets an ephemeral notice rather than the modal.
        assert not mock_slack_client.views_open.called
        assert mock_slack_client.chat_postEphemeral.called or mock_slack_client.chat_postMessage.called


class TestResetPersonal:
    def test_clears_ai_fields_and_republishes(self, slack_integration, mock_slack_client, flag_on, admin_user):
        SlackSettings.objects.create(
            default_integration=slack_integration,
            slack_workspace_id=SLACK_WORKSPACE_ID,
            slack_user_id="U001",
            ai_preferences={"runtime_adapter": "claude", "model": "claude-opus-4-7", "reasoning_effort": "high"},
        )
        payload = _block_action_payload(
            action_id=ACTION_RESET_PERSONAL,
            slack_user_id="U001",
            trigger_id="trig.4",
        )
        handle_ai_preferences_block_action(payload, payload["actions"][0])

        row = SlackSettings.objects.get(slack_workspace_id=SLACK_WORKSPACE_ID, slack_user_id="U001")
        assert row.runtime_adapter is None
        assert row.model is None
        assert row.reasoning_effort is None
        assert mock_slack_client.views_publish.called


class TestResetProjectPersonal:
    def test_clears_routing_only_when_ai_preferences_present(
        self, slack_integration, mock_slack_client, flag_on, admin_user
    ):
        # Mixed row → reset clears routing, AI fields stay.
        SlackSettings.objects.create(
            default_integration=slack_integration,
            slack_workspace_id=SLACK_WORKSPACE_ID,
            slack_user_id="U001",
            ai_preferences={"runtime_adapter": "claude", "model": "claude-opus-4-7", "reasoning_effort": "high"},
        )
        payload = _block_action_payload(
            action_id=ACTION_RESET_PROJECT_PERSONAL,
            slack_user_id="U001",
            trigger_id="trig.5",
        )
        handle_ai_preferences_block_action(payload, payload["actions"][0])

        row = SlackSettings.objects.get(slack_workspace_id=SLACK_WORKSPACE_ID, slack_user_id="U001")
        assert row.default_integration_id is None
        assert row.runtime_adapter == "claude"
        assert row.model == "claude-opus-4-7"
        assert row.reasoning_effort == "high"
        assert mock_slack_client.views_publish.called

    def test_deletes_row_when_no_ai_preferences_remain(self, slack_integration, mock_slack_client, flag_on, admin_user):
        # Routing-only row → reset drops it so the resolver falls back to
        # the workspace default cleanly.
        SlackSettings.objects.create(
            default_integration=slack_integration,
            slack_workspace_id=SLACK_WORKSPACE_ID,
            slack_user_id="U002",
        )
        payload = _block_action_payload(
            action_id=ACTION_RESET_PROJECT_PERSONAL,
            slack_user_id="U002",
            trigger_id="trig.6",
        )
        handle_ai_preferences_block_action(payload, payload["actions"][0])

        assert not SlackSettings.objects.filter(slack_workspace_id=SLACK_WORKSPACE_ID, slack_user_id="U002").exists()
        assert mock_slack_client.views_publish.called

    def test_no_row_is_a_noop(self, slack_integration, mock_slack_client, flag_on, admin_user):
        payload = _block_action_payload(
            action_id=ACTION_RESET_PROJECT_PERSONAL,
            slack_user_id="U003",
            trigger_id="trig.7",
        )
        handle_ai_preferences_block_action(payload, payload["actions"][0])
        # Nothing to clear — still republish so the view stays in sync.
        assert mock_slack_client.views_publish.called


# ---------------------------------------------------------------------------
# Handler tests — view_submission
# ---------------------------------------------------------------------------


class TestPersonalSubmit:
    def test_writes_row_and_republishes(self, slack_integration, mock_slack_client, flag_on, admin_user):
        payload = _view_submission_payload(
            callback_id=EDIT_MODAL_PERSONAL_CALLBACK_ID,
            slack_user_id="U001",
            runtime_adapter="claude",
            model="claude-opus-4-7",
            effort="high",
        )
        response = handle_app_home_view_submission(payload)
        assert response.status_code == 200
        assert json.loads(response.content) == {"response_action": "clear"}

        row = SlackSettings.objects.get(slack_workspace_id=SLACK_WORKSPACE_ID, slack_user_id="U001")
        assert row.runtime_adapter == "claude"
        assert row.model == "claude-opus-4-7"
        assert row.reasoning_effort == "high"
        assert mock_slack_client.views_publish.called

    def test_invalid_pair_keeps_modal_open_with_error(self, slack_integration, mock_slack_client, flag_on):
        # `xhigh` isn't supported on claude-sonnet-4-6 — validate_ai_preferences rejects.
        payload = _view_submission_payload(
            callback_id=EDIT_MODAL_PERSONAL_CALLBACK_ID,
            slack_user_id="U001",
            runtime_adapter="claude",
            model="claude-sonnet-4-6",
            effort="xhigh",
        )
        response = handle_app_home_view_submission(payload)
        body = json.loads(response.content)
        assert body["response_action"] == "errors"
        assert MODAL_BLOCK_RUNTIME_ADAPTER in body["errors"]
        # Modal left open: no row written, no publish.
        assert not SlackSettings.objects.filter(slack_user_id="U001").exists()


class TestWorkspaceSubmitAdminGate:
    def test_non_admin_blocked(self, slack_integration, mock_slack_client, flag_on, non_admin_user):
        payload = _view_submission_payload(
            callback_id=EDIT_MODAL_WORKSPACE_CALLBACK_ID,
            slack_user_id="U_NONADMIN",
            runtime_adapter="claude",
            model="claude-opus-4-7",
            effort="high",
        )
        response = handle_app_home_view_submission(payload)
        body = json.loads(response.content)
        assert body["response_action"] == "errors"
        assert not SlackSettings.objects.filter(slack_user_id__isnull=True).exists()
