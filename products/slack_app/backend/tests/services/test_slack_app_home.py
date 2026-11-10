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
import importlib
from dataclasses import dataclass
from datetime import UTC, datetime, time
from types import ModuleType
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.logic.feature_tips.state import get_state, set_tips_enabled
from products.slack_app.backend.logic.interview_recruitment import (
    INTERVIEW_BOOK_ACTION_ID,
    INVITE_MESSAGE,
    book_button,
    invite_section,
)
from products.slack_app.backend.models import (
    ChannelWelcomeMode,
    SlackDailyFocus,
    SlackSettings,
    SlackThreadTaskMapping,
    SlackUserProfileCache,
    ThreadJoinMode,
    UntaggedFollowupMode,
)
from products.slack_app.backend.services import slack_app_home
from products.slack_app.backend.services.slack_app_home import (
    ACTION_EDIT_PERSONAL,
    ACTION_RESET_PERSONAL,
    ACTION_RESET_PROJECT_PERSONAL,
    ACTION_SET_AUTO_MODEL_CHOICE,
    ACTION_SET_CHANNEL_WELCOME_MODE,
    ACTION_SET_DAILY_FOCUS,
    ACTION_SET_DAILY_FOCUS_TIME,
    ACTION_SET_FEATURE_TIPS,
    ACTION_SET_PROJECT_WORKSPACE,
    ACTION_SET_THREAD_JOIN_MODE,
    ACTION_SET_UNTAGGED_FOLLOWUP_MODE,
    ACTION_TASKS_FILTER_REPO,
    ACTION_TASKS_PAGE_NEXT,
    ACTION_TASKS_PAGE_PREV,
    ACTION_UNLINK_ACCOUNT,
    AUTO_MODEL_CHOICE_VALUE,
    BLOCK_TASKS_CONTROLS,
    EDIT_MODAL_PERSONAL_CALLBACK_ID,
    FEATURE_TIPS_VALUE,
    HOME_ACTION_IDS,
    MODAL_ACTION_MODEL,
    MODAL_ACTION_REASONING_EFFORT,
    MODAL_ACTION_RUNTIME_ADAPTER,
    MODAL_BLOCK_MODEL,
    MODAL_BLOCK_REASONING_EFFORT,
    MODAL_BLOCK_RUNTIME_ADAPTER,
    AccountState,
    DailyFocusHomeState,
    GitHubAccount,
    GitHubState,
    OwnPlanState,
    ProjectChoice,
    ProjectState,
    RunDefaultsState,
    StatsState,
    TaskItem,
    TasksState,
    handle_ai_preferences_block_action,
    handle_app_home_opened,
    handle_app_home_view_submission,
    parse_modal_submission,
    render_edit_modal,
    render_home_view,
)
from products.slack_app.backend.services.slack_settings import AIPreferences
from products.tasks.backend.facade.ai_run_defaults import get_user_ai_run_preferences, update_user_ai_run_preferences
from products.tasks.backend.models import Task, TaskRun

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


@pytest.fixture(autouse=True)
def _stub_picker_facade():
    """Stub the tasks run-config facade and the LLM-gateway model fetch.

    The facade pulls in `tasks.temporal` on import, which the test env can't
    satisfy. The gateway fetch would hit a real network. Both are replaced with
    deterministic in-memory fakes covering every model the renderer and handler
    tests reference.
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
    public_efforts = ("low", "medium", "high", "xhigh", "max")

    def fake_get_supported(adapter, model):
        adapter_value = adapter.value if hasattr(adapter, "value") else adapter
        return tuple(_Effort(v) for v in supported_by_model.get((adapter_value, model), ()))

    def fake_get_error(adapter, model, effort):
        if adapter is None or model is None or effort is None:
            return None
        if effort in supported_by_model.get((adapter, model), ()):
            return None
        return f"Effort '{effort}' not supported on {model}."

    # The catalogue derives the gateway-provider → adapter mapping and the adapter for
    # a given model from the tasks product rather than restating them, so the stub has
    # to answer both.
    providers_by_adapter = {"claude": "anthropic", "codex": "openai"}
    models_by_adapter = {
        "claude": ("claude-opus-4-7", "claude-sonnet-4-6"),
        "codex": ("gpt-5", "gpt-5.5"),
    }

    def _adapter_value(adapter):
        return adapter.value if hasattr(adapter, "value") else adapter

    def fake_get_provider(adapter):
        provider = providers_by_adapter.get(_adapter_value(adapter))
        return _Adapter(provider) if provider else None

    def fake_get_models(adapter):
        return models_by_adapter.get(_adapter_value(adapter), ())

    def fake_validate_selection(adapter, model, effort):
        adapter_value = _adapter_value(adapter)
        if adapter_value is not None and adapter_value not in models_by_adapter:
            raise ValidationError(f"Unknown runtime_adapter '{adapter_value}'.")
        owning = next((a for a, models in models_by_adapter.items() if model in models), None)
        if adapter_value is not None and owning is not None and owning != adapter_value:
            raise ValidationError(f"Model '{model}' runs on runtime_adapter '{owning}', not '{adapter_value}'.")
        error = fake_get_error(adapter_value, model, effort)
        if error:
            raise ValidationError(error)

    facade_name = "products.tasks.backend.facade.run_config"
    # `Any` annotation so mypy accepts the stub-attribute assignments below —
    # the stdlib `ModuleType` rejects them outright, and ruff B010 reverts any
    # `setattr` workaround back to attribute syntax.
    fake: Any = ModuleType(facade_name)
    # Seed from the real module so overriding a handful of functions doesn't hide the
    # rest of its namespace from anything else that imports it while the swap is in
    # place — the tasks serializers pull a dozen constants from here.
    fake.__dict__.update(vars(importlib.import_module(facade_name)))
    fake.RuntimeAdapter = _RuntimeAdapter()
    fake.get_supported_reasoning_efforts = fake_get_supported
    fake.get_reasoning_effort_error = fake_get_error
    fake.get_provider_for_runtime_adapter = fake_get_provider
    fake.get_models_for_runtime_adapter = fake_get_models
    fake.validate_model_selection = fake_validate_selection
    fake.REASONING_EFFORTS = public_efforts

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
    # The catalogue reads the run-config internals directly rather than through the facade,
    # so those lookups are replaced one at a time. Standing the facade stub in for the whole
    # module would blank every other name on it — the GitHub helpers `facade.api` defers to
    # among them.
    utils_name = "products.tasks.backend.temporal.process_task.utils"
    model_catalogue = importlib.import_module("products.tasks.backend.logic.services.model_catalogue")

    saved_facade = sys.modules.get(facade_name)
    sys.modules[facade_name] = fake
    # The provider → adapter map is cached for the process, so the fake only governs once
    # the cache is dropped on the way in and back out.
    model_catalogue._runtime_adapter_by_provider.cache_clear()
    try:
        with (
            patch(f"{utils_name}.get_supported_reasoning_efforts", fake_get_supported),
            patch(f"{utils_name}.get_provider_for_runtime_adapter", fake_get_provider),
            patch.object(model_catalogue, "list_gateway_models", return_value=gateway_models),
        ):
            yield
    finally:
        model_catalogue._runtime_adapter_by_provider.cache_clear()
        if saved_facade is None:
            sys.modules.pop(facade_name, None)
        else:
            sys.modules[facade_name] = saved_facade


# ---------------------------------------------------------------------------
# Renderer helpers
# ---------------------------------------------------------------------------


def _action_ids(view: dict) -> list[str]:
    out: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if "action_id" in node:
                out.append(node["action_id"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(view["blocks"])
    return out


def _block_ids(view: dict) -> list[str]:
    return [b.get("block_id") for b in view["blocks"] if b.get("block_id")]


def _find_block(view: dict, block_prefix: str) -> dict | None:
    """The block rendered under `block_prefix` — matching the runtime/model suffix the
    modal scopes its dependent blocks with."""
    for block in view["blocks"]:
        block_id = block.get("block_id") or ""
        if block_id == block_prefix or block_id.startswith(f"{block_prefix}:"):
            return block
    return None


def _option_objects(view: dict) -> list[dict]:
    out: list[dict] = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("options", "initial_options") and isinstance(value, list):
                    out.extend(option for option in value if isinstance(option, dict))
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(view["blocks"])
    return out


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


def _modal_state(*, runtime_adapter=None, model=None, effort=None) -> dict:
    """View state as Slack sends it back — dependent blocks under the scoped ids the
    modal rendered them with."""
    state: dict = {}
    if runtime_adapter:
        state[MODAL_BLOCK_RUNTIME_ADAPTER] = {
            MODAL_ACTION_RUNTIME_ADAPTER: {"selected_option": {"value": runtime_adapter}}
        }
    if model:
        state[f"{MODAL_BLOCK_MODEL}:{runtime_adapter}"] = {MODAL_ACTION_MODEL: {"selected_option": {"value": model}}}
    if effort:
        state[f"{MODAL_BLOCK_REASONING_EFFORT}:{model}"] = {
            MODAL_ACTION_REASONING_EFFORT: {"selected_option": {"value": effort}}
        }
    return state


def _build_submission(*, runtime_adapter=None, model=None, effort=None) -> dict:
    return {"state": {"values": _modal_state(runtime_adapter=runtime_adapter, model=model, effort=effort)}}


# ---------------------------------------------------------------------------
# Handler helpers
# ---------------------------------------------------------------------------


def _block_action_payload(
    *,
    action_id: str,
    slack_user_id: str,
    trigger_id: str | None = None,
    channel: str | None = None,
    selected_value: str | None = None,
) -> dict:
    action: dict[str, Any] = {"action_id": action_id}
    if selected_value is not None:
        action["selected_option"] = {"value": selected_value}
    return {
        "type": "block_actions",
        "team": {"id": SLACK_WORKSPACE_ID},
        "user": {"id": slack_user_id},
        "trigger_id": trigger_id,
        "channel": {"id": channel} if channel else None,
        "actions": [action],
    }


def _tasks_click_payload(action_id: str, *, value: str | None = None, repo: str | None = None) -> dict:
    """A Home tab Tasks click: the page rides on the button's value, the filter on view state."""
    action: dict[str, Any] = {"action_id": action_id}
    if value is not None:
        action["value"] = value
    controls: dict[str, Any] = {}
    if repo:
        controls[ACTION_TASKS_FILTER_REPO] = {"selected_option": {"value": repo}}
    return {
        "type": "block_actions",
        "team": {"id": SLACK_WORKSPACE_ID},
        "user": {"id": "U001"},
        "actions": [action],
        "view": {"id": "V1", "hash": "H1", "type": "home", "state": {"values": {BLOCK_TASKS_CONTROLS: controls}}},
    }


def _view_submission_payload(
    *,
    callback_id: str,
    slack_user_id: str,
    runtime_adapter: str | None,
    model: str | None,
    effort: str | None,
) -> dict:
    state = _modal_state(runtime_adapter=runtime_adapter, model=model, effort=effort)
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
    @pytest.mark.parametrize("is_admin", [False, True])
    def test_empty_state_renders_buttons_and_no_reset(self, is_admin):
        view = render_home_view(is_admin=is_admin)
        assert view["type"] == "home"
        ids = _action_ids(view)
        # Personal edit always present; reset hidden when no override. Admins get
        # no extra model control — the model is purely a personal preference.
        assert ACTION_EDIT_PERSONAL in ids
        assert ACTION_RESET_PERSONAL not in ids

    def test_reset_shows_when_the_viewer_has_a_personal_default(self):
        view = render_home_view(
            is_admin=False,
            run_defaults=RunDefaultsState(model="claude-opus-4-7", runtime_adapter="claude", source="user"),
        )
        assert ACTION_RESET_PERSONAL in _action_ids(view)

    def test_active_model_summary_mentions_model_label(self):
        view = render_home_view(
            is_admin=True,
            run_defaults=RunDefaultsState(model="claude-opus-4-7", runtime_adapter="claude", source="user"),
        )
        text_blob = " ".join(block["text"]["text"] for block in view["blocks"] if block.get("type") == "section")
        # Friendly label rather than raw model id; source attribution visible.
        assert "Claude Opus 4.7" in text_blob
        assert "Your PostHog default" in _all_text(view)

    def _every_card_view(self, *, auto_model_choice: bool = False) -> dict:
        return render_home_view(
            is_admin=True,
            run_defaults=RunDefaultsState(model="claude-opus-4-7", runtime_adapter="claude", source="user"),
            account_state=AccountState(enabled=True, link_url="https://app/link"),
            github_state=GitHubState(user_resolved=True, settings_url="https://app/settings"),
            project_state=ProjectState(
                candidates=(ProjectChoice(team_id=1, label="Org · Team"),),
                personal_team_id=1,
                workspace_team_id=1,
                workspace_team_label="Org · Team",
            ),
            tasks_state=TasksState(
                items=(
                    TaskItem(
                        title="Fix flaky retention test",
                        posthog_url="https://app/project/1/tasks/abc",
                        desktop_url=None,
                        status="in_progress",
                        repository="posthog/posthog",
                        pr_url=None,
                        thread_url=None,
                        updated_at_label="5m ago",
                    ),
                ),
                available_repos=("posthog/posthog",),
                has_any_tasks=True,
                page=1,
                total_pages=3,
                total_filtered=25,
            ),
            stats_state=StatsState(tasks_started=4, tasks_with_pr=2, tasks_merged=1, active_people=2),
            untagged_followup_mode=UntaggedFollowupMode.AUTO,
            untagged_question_mode=UntaggedFollowupMode.ASK,
            channel_welcome_mode=ChannelWelcomeMode.CHANNEL,
            auto_model_choice=auto_model_choice,
            own_plan=OwnPlanState(connected=True, settings_url="https://app.example.com/settings"),
            thread_join_mode=ThreadJoinMode.ASK_PER_THREAD,
            feature_tips_enabled=auto_model_choice,
            daily_focus=DailyFocusHomeState(enabled=auto_model_choice, at=time(9, 0), zone="Europe/Prague"),
            interview_invite=invite_section(INVITE_MESSAGE, book_button(1, "home")),
        )

    @pytest.mark.parametrize("is_admin", [False, True])
    def test_workspace_default_remains_visible_without_project_options(self, is_admin):
        view = render_home_view(
            is_admin=is_admin,
            project_state=ProjectState(workspace_team_id=1, workspace_team_label="Example project"),
        )
        assert "Workspace default: Example project" in _all_text(view)
        assert ACTION_SET_PROJECT_WORKSPACE not in _action_ids(view)

    def test_full_admin_view_keeps_failed_tasks_and_controls_within_block_limit(self):
        item = TaskItem(
            title="Task <example> & check",
            posthog_url="https://example.com/tasks/1",
            desktop_url=None,
            status="failed",
            repository="example/site",
            pr_url=None,
            thread_url="https://example.com/thread",
            updated_at_label="1h ago",
            error_message="Build failed",
        )
        from products.slack_app.backend.services.slack_app_home_stats import ModelUsage, PersonRow, Slice, TrendBucket

        original = render_home_view
        with patch.object(
            sys.modules[__name__],
            "render_home_view",
            side_effect=lambda **kwargs: original(
                **{
                    **kwargs,
                    "tasks_state": TasksState(
                        items=(item,) * 10,
                        has_any_tasks=True,
                        available_repos=("example/site",),
                        page=1,
                        total_pages=3,
                        total_filtered=30,
                        refreshed_at_epoch=1,
                    ),
                    "stats_state": StatsState(
                        tasks_started=30,
                        tasks_with_pr=10,
                        outcomes=(Slice("Failed", 30),),
                        trend=(TrendBucket("Nov 01", 10, 2),),
                        models=(ModelUsage("claude-opus-4-7", "claude", 30),),
                        people=(PersonRow("Example person", 30, 2),),
                        truncated=True,
                        refreshed_at_epoch=1,
                    ),
                }
            ),
        ):
            view = self._every_card_view(auto_model_choice=True)
        assert len(view["blocks"]) <= 100
        assert _all_text(view).count("Task &lt;example&gt; &amp; check") == 10
        assert _all_text(view).count("Build failed") == 10
        assert set(_action_ids(view)) == (HOME_ACTION_IDS - {ACTION_UNLINK_ACCOUNT}) | {INTERVIEW_BOOK_ACTION_ID}

    @pytest.mark.parametrize("connected", [True, False])
    def test_chatgpt_plan_keeps_connection_details_under_linked_accounts(self, connected):
        view = render_home_view(
            is_admin=False, own_plan=OwnPlanState(connected=connected, settings_url="https://example.com/settings")
        )
        text = _all_text(view)
        assert text.index("Linked accounts") < text.index("ChatGPT plan")
        assert ("use your ChatGPT plan, also when other people join your thread" in text) is connected
        assert ("Connect your ChatGPT plan" in text) is not connected

    def test_every_control_the_tab_renders_is_routable(self):
        # The interactivity endpoint claims region ownership and dispatches off
        # HOME_ACTION_IDS, so a control missing from it renders as a button that
        # silently does nothing. Render every card at once and check the whole set.
        view = self._every_card_view()

        # Equality both ways: an unroutable control fails on the left, and a card that
        # stopped rendering fails on the right instead of passing a subset check trivially.
        # Unlink only renders once an account is linked, which this fixture deliberately isn't.
        assert set(_action_ids(view)) == (HOME_ACTION_IDS - {ACTION_UNLINK_ACCOUNT}) | {INTERVIEW_BOOK_ACTION_ID}

    @pytest.mark.parametrize("auto_model_choice", [False, True])
    def test_every_option_stays_within_the_limits_slack_enforces(self, auto_model_choice):
        # `views.publish` validates the whole payload, so one over-long label or
        # description costs the entire tab: Slack returns `invalid_arguments` and the
        # viewer keeps whatever was published last. Checked options carry a second copy
        # of the option object under `initial_options`, hence both renders.
        view = self._every_card_view(auto_model_choice=auto_model_choice)

        oversized = [
            (option["value"], field, len(option[field]["text"]))
            for option in _option_objects(view)
            for field, limit in (("text", 75), ("description", 75))
            if field in option and len(option[field]["text"]) > limit
        ]
        assert oversized == []


class TestThreadFollowupsCard:
    def _view(self, mode) -> dict:
        return render_home_view(is_admin=False, untagged_followup_mode=mode)

    def test_card_absent_where_untagged_followups_do_not_run(self):
        # Nothing to configure when replies are never picked up in the first place.
        view = self._view(None)
        assert ACTION_SET_UNTAGGED_FOLLOWUP_MODE not in _action_ids(view)

    @pytest.mark.parametrize("mode", list(UntaggedFollowupMode))
    def test_picker_preselects_the_stored_mode(self, mode):
        # Without the right initial option the tab misreports the setting, and picking
        # the value already stored is a no-op click that looks broken.
        view = self._view(mode)
        select = next(
            element
            for block in view["blocks"]
            for element in block.get("elements", [])
            if element.get("action_id") == ACTION_SET_UNTAGGED_FOLLOWUP_MODE
        )
        assert select["initial_option"]["value"] == mode.value
        assert {o["value"] for o in select["options"]} == set(UntaggedFollowupMode.values)


class TestThreadFollowupsPicker:
    def _pick(self, value: str) -> dict:
        return {
            "type": "block_actions",
            "team": {"id": SLACK_WORKSPACE_ID},
            "user": {"id": "U001"},
            "actions": [
                {"action_id": ACTION_SET_UNTAGGED_FOLLOWUP_MODE, "selected_option": {"value": value}},
            ],
        }

    @pytest.mark.parametrize(
        "picked,expected",
        [
            (UntaggedFollowupMode.ASK.value, UntaggedFollowupMode.ASK.value),
            (UntaggedFollowupMode.NEVER.value, UntaggedFollowupMode.NEVER.value),
            (UntaggedFollowupMode.AUTO.value, UntaggedFollowupMode.AUTO.value),
            # A value the tab never rendered isn't worth persisting — it would read
            # back as `auto` anyway, but only after a round trip through the DB.
            ("something-else", None),
        ],
    )
    def test_pick_is_persisted_against_the_clicking_user(
        self, slack_integration, mock_slack_client, flag_on, picked, expected
    ):
        payload = self._pick(picked)
        with patch("products.slack_app.backend.services.slack_app_home.is_slack_workspace_admin", return_value=False):
            handle_ai_preferences_block_action(payload, payload["actions"][0])

        row = SlackSettings.objects.filter(slack_workspace_id=SLACK_WORKSPACE_ID, slack_user_id="U001").first()
        assert (row.untagged_followup_mode if row else None) == expected
        assert mock_slack_client.views_publish.called


class TestAutoModelChoiceToggle:
    def _toggle(self, checked: bool) -> dict:
        selected = [{"value": AUTO_MODEL_CHOICE_VALUE}] if checked else []
        return {
            "type": "block_actions",
            "team": {"id": SLACK_WORKSPACE_ID},
            "user": {"id": "U001"},
            "actions": [{"action_id": ACTION_SET_AUTO_MODEL_CHOICE, "selected_options": selected}],
        }

    @pytest.mark.parametrize(
        "linked,checked,expected",
        [
            (True, True, True),
            (True, False, False),
            # The router runs as a PostHog user, so a viewer with no linked user must not opt in.
            (False, True, None),
        ],
    )
    def test_toggle_is_stored_for_the_clicking_user_only_when_linked_to_a_posthog_user(
        self, slack_integration, mock_slack_client, linked, checked, expected
    ):
        if linked:
            User.objects.create_and_join(slack_integration.team.organization, "mapped@example.com", None)
        SlackUserProfileCache.objects.create(
            integration=slack_integration, slack_user_id="U001", email="mapped@example.com"
        )
        payload = self._toggle(checked)
        with patch("products.slack_app.backend.services.slack_app_home.is_slack_workspace_admin", return_value=False):
            handle_ai_preferences_block_action(payload, payload["actions"][0])

        row = SlackSettings.objects.filter(slack_workspace_id=SLACK_WORKSPACE_ID, slack_user_id="U001").first()
        assert (row.auto_model_choice if row else None) == expected
        assert mock_slack_client.views_publish.called


class TestFeatureTipsToggle:
    @pytest.mark.parametrize("checked", [True, False])
    def test_toggle_is_stored_for_the_clicking_user(self, slack_integration, mock_slack_client, checked):
        set_tips_enabled(SLACK_WORKSPACE_ID, "U001", not checked)
        selected = [{"value": FEATURE_TIPS_VALUE}] if checked else []
        action = {"action_id": ACTION_SET_FEATURE_TIPS, "selected_options": selected}
        payload = {
            "type": "block_actions",
            "team": {"id": SLACK_WORKSPACE_ID},
            "user": {"id": "U001"},
            "actions": [action],
        }
        with patch("products.slack_app.backend.services.slack_app_home.is_slack_workspace_admin", return_value=False):
            handle_ai_preferences_block_action(payload, action)

        assert (get_state(SLACK_WORKSPACE_ID, "U001").opted_out_at is None) is checked
        assert mock_slack_client.views_publish.called


class TestDailyFocusControls:
    @pytest.mark.parametrize(
        "scopes, action, stored, expected_next_run",
        [
            (
                "search:read.public",
                {"selected_options": [{"value": "on"}]},
                True,
                datetime(2026, 11, 10, 8, 0, tzinfo=UTC),
            ),
            # Off keeps the row, so a later onboarding does not turn it back on.
            ("search:read.public", {"selected_options": []}, True, None),
            # The link cannot search, so a stale view must not turn on a run that cannot work.
            ("users:read", {"selected_options": [{"value": "on"}]}, False, None),
        ],
    )
    def test_the_checkbox_turns_the_daily_work_focus_on_and_off(
        self,
        slack_integration,
        mock_slack_client,
        flag_on,
        link_user,
        scopes,
        action,
        stored,
        expected_next_run,
    ):
        self._link(slack_integration, link_user, scopes)
        action = {"action_id": ACTION_SET_DAILY_FOCUS, **action}

        with time_machine.travel(datetime(2026, 11, 9, 12, 0, tzinfo=UTC), tick=False):
            self._click(action)

        row = (
            SlackDailyFocus.objects.unscoped()
            .filter(slack_workspace_id=SLACK_WORKSPACE_ID, slack_user_id="U001")
            .first()
        )
        assert (row is not None) is stored
        assert (row.next_run_at if row else None) == expected_next_run

    @pytest.mark.parametrize(
        "last_run_at, expected_next_run",
        [
            # Still today, because the click at 13:00 in Prague comes before 14:30.
            (datetime(2026, 11, 6, 8, 0, tzinfo=UTC), datetime(2026, 11, 9, 13, 30, tzinfo=UTC)),
            # Today's 09:00 run already went out, so the new time starts tomorrow, not with a second DM today.
            (datetime(2026, 11, 9, 8, 0, tzinfo=UTC), datetime(2026, 11, 10, 13, 30, tzinfo=UTC)),
        ],
    )
    def test_a_new_time_moves_the_next_run(
        self, slack_integration, mock_slack_client, flag_on, link_user, last_run_at, expected_next_run
    ):
        self._link(slack_integration, link_user, "search:read.public")
        SlackDailyFocus.objects.for_team(slack_integration.team_id).create(
            team_id=slack_integration.team_id,
            slack_workspace_id=SLACK_WORKSPACE_ID,
            slack_user_id="U001",
            integration_id=slack_integration.id,
            next_run_at=datetime(2026, 11, 10, 8, 0, tzinfo=UTC),
            last_run_at=last_run_at,
        )

        with time_machine.travel(datetime(2026, 11, 9, 12, 0, tzinfo=UTC), tick=False):
            self._click({"action_id": ACTION_SET_DAILY_FOCUS_TIME, "selected_time": "14:30"})

        row = SlackDailyFocus.objects.unscoped().get(slack_workspace_id=SLACK_WORKSPACE_ID, slack_user_id="U001")
        assert row.at == time(14, 30)
        assert row.next_run_at == expected_next_run

    def _link(self, slack_integration, link_user, scopes: str) -> None:
        user = User.objects.create_and_join(slack_integration.team.organization, "daily@example.com", None)
        link_user(user, slack_user_id="U001", slack_team_id=SLACK_WORKSPACE_ID, user_scopes=scopes)
        # Fresh at the pinned noon below, so the click reads the timezone without calling Slack.
        SlackUserProfileCache.objects.create(
            integration=slack_integration,
            slack_user_id="U001",
            tz="Europe/Prague",
            refreshed_at=datetime(2026, 11, 9, 11, 30, tzinfo=UTC),
        )

    def _click(self, action: dict) -> None:
        payload = {
            "type": "block_actions",
            "team": {"id": SLACK_WORKSPACE_ID},
            "user": {"id": "U001"},
            "actions": [action],
        }
        with (
            patch("products.slack_app.backend.services.slack_app_home.is_slack_workspace_admin", return_value=False),
            patch("products.slack_app.backend.logic.daily_focus.capture_slack_event"),
        ):
            handle_ai_preferences_block_action(payload, action)


class TestChannelWelcomePicker:
    def test_card_is_hidden_from_non_admins(self):
        view = render_home_view(is_admin=False, channel_welcome_mode=ChannelWelcomeMode.CHANNEL)
        assert ACTION_SET_CHANNEL_WELCOME_MODE not in _action_ids(view)

    @pytest.mark.parametrize(
        "is_admin,picked,expected",
        [
            (True, ChannelWelcomeMode.OFF.value, ChannelWelcomeMode.OFF.value),
            (True, ChannelWelcomeMode.INVITER.value, ChannelWelcomeMode.INVITER.value),
            (True, "something-else", None),
            # A stale view or a hand-crafted payload must not change a workspace setting.
            (False, ChannelWelcomeMode.OFF.value, None),
        ],
    )
    def test_pick_is_stored_on_the_workspace_row_for_admins_only(
        self, slack_integration, mock_slack_client, flag_on, is_admin, picked, expected
    ):
        payload = _block_action_payload(
            action_id=ACTION_SET_CHANNEL_WELCOME_MODE, slack_user_id="U001", selected_value=picked
        )
        with patch(
            "products.slack_app.backend.services.slack_app_home.is_slack_workspace_admin", return_value=is_admin
        ):
            handle_ai_preferences_block_action(payload, payload["actions"][0])

        row = SlackSettings.objects.filter(slack_workspace_id=SLACK_WORKSPACE_ID, slack_user_id=None).first()
        assert (row.channel_welcome_mode if row else None) == expected
        assert not SlackSettings.objects.filter(slack_workspace_id=SLACK_WORKSPACE_ID, slack_user_id="U001").exists()


class TestLinkedAccountsCard:
    def _view(self, *, account_state=None, github_state=None) -> dict:
        return render_home_view(is_admin=False, account_state=account_state, github_state=github_state)

    def _rows(self, view: dict) -> list[tuple[str, dict | None]]:
        rows = []
        for index, block in enumerate(view["blocks"]):
            if block.get("type") == "section" and block["text"]["text"].startswith(("*PostHog*", "*GitHub*")):
                text = block["text"]["text"] + "\n" + _all_text(view["blocks"][index + 1])
                following = view["blocks"][index + 2] if index + 2 < len(view["blocks"]) else {}
                button = following["elements"][0] if following.get("type") == "actions" else None
                rows.append((text, button))
        return rows

    def _row(self, view: dict, prefix: str) -> tuple[str, dict | None]:
        return next(row for row in self._rows(view) if row[0].startswith(prefix))

    @pytest.mark.parametrize(
        "user_resolved,connected,credentials_usable,expected_button,expected_style",
        [
            (True, True, True, "Manage GitHub", None),
            # A row whose tokens went stale is what the task flow refuses to run on,
            # so the card has to ask for a reconnect rather than read as connected.
            (True, True, False, "Reconnect GitHub", "primary"),
            (True, False, False, "Connect GitHub", "primary"),
            (False, False, False, None, None),
        ],
    )
    def test_github_button_matches_connection_state(
        self, user_resolved, connected, credentials_usable, expected_button, expected_style
    ):
        accounts = (GitHubAccount(installation_id="1", login="octocat", account_name="octocat"),) if connected else ()
        view = self._view(
            github_state=GitHubState(
                user_resolved=user_resolved,
                accounts=accounts,
                credentials_usable=credentials_usable,
                settings_url="https://app/project/1/settings/user-personal-integrations",
            )
        )
        text, button = self._row(view, "*GitHub*")
        if expected_button is None:
            # Without a resolved PostHog user we can't say anything about their
            # GitHub, so the row points at account linking instead.
            assert button is None
            assert "Link your PostHog account first" in _all_text(view)
            return
        assert button is not None
        assert button["text"]["text"] == expected_button
        assert button["url"] == "https://app/project/1/settings/user-personal-integrations"
        assert button.get("style") == expected_style
        if connected:
            assert ("Connected as" in text) is credentials_usable
            assert ("Access expired:" in text) is not credentials_usable

    def test_every_connected_installation_is_listed(self):
        view = self._view(
            github_state=GitHubState(
                user_resolved=True,
                accounts=(
                    GitHubAccount(installation_id="1", login="octocat", account_name="octocat"),
                    GitHubAccount(installation_id="2", login="octocat", account_name="PostHog"),
                ),
                credentials_usable=True,
                settings_url="https://app/settings",
            )
        )
        text, _button = self._row(view, "*GitHub*")
        assert "`octocat`" in text
        # Installation on an org the login differs from names both sides.
        assert "`octocat` on *PostHog*" in text

    def test_each_account_carries_its_own_button(self):
        view = self._view(
            account_state=AccountState(enabled=True, linked_email="user@posthog.com"),
            github_state=GitHubState(user_resolved=True, settings_url="https://app/settings"),
        )
        rows = self._rows(view)
        assert [text.split("\n")[0] for text, _ in rows] == ["*PostHog*", "*GitHub*"]
        # Disconnect belongs to the PostHog row, Connect GitHub to its own.
        assert rows[0][1] is not None and rows[0][1]["action_id"] == ACTION_UNLINK_ACCOUNT
        assert rows[1][1] is not None and rows[1][1]["text"]["text"] == "Connect GitHub"

    def test_github_row_stands_alone_when_account_linking_is_off(self):
        view = self._view(
            account_state=AccountState(enabled=False),
            github_state=GitHubState(user_resolved=True, settings_url="https://app/settings"),
        )
        rows = self._rows(view)
        assert len(rows) == 1
        assert rows[0][0].startswith("*GitHub*")
        assert ACTION_UNLINK_ACCOUNT not in _all_text(view)


_TASK_TITLES = ("Fix flaky retention test", "Refactor mention dispatcher")


class TestTasksCard:
    def _kwargs(self, **overrides):
        base = {
            "is_admin": False,
        }
        base.update(overrides)
        return base

    def _item(self, **overrides) -> TaskItem:
        defaults: dict[str, Any] = {
            "title": "Fix flaky retention test",
            "posthog_url": "https://app/project/1/tasks/abc",
            "desktop_url": None,
            "status": "in_progress",
            "repository": "posthog/posthog",
            "pr_url": "https://github.com/posthog/posthog/pull/123",
            "thread_url": "https://slack.com/archives/C1/p1234567890123456",
            "updated_at_label": "5m ago",
        }
        defaults.update(overrides)
        return TaskItem(**defaults)

    def _task_items(self, view: dict, expected_count: int) -> list[tuple[str, str]]:
        items = []
        for index, block in enumerate(view["blocks"]):
            text = block.get("text", {}).get("text", "")
            if block["type"] == "section" and text in [f"*{title}*" for title in _TASK_TITLES]:
                detail = []
                for following in view["blocks"][index + 1 :]:
                    if following["type"] != "context":
                        break
                    detail.append(_all_text(following))
                items.append((text, "\n\n".join(detail)))
        assert len(items) == expected_count
        return items

    def test_card_hidden_when_state_is_none(self):
        view = render_home_view(**self._kwargs())
        assert "Tasks" not in _all_text(view)

    def test_first_use_state_invites_user_to_mention(self):
        view = render_home_view(**self._kwargs(tasks_state=TasksState()))
        text = _all_text(view)
        assert "*Tasks*" in text
        assert "Mention @PostHog" in text

    @pytest.mark.parametrize(
        "status,label,image",
        [
            ("in_progress", "In progress", "todo_doing"),
            ("completed", "Done", "todo_done"),
            ("failed", "Failed", "todo_cancel"),
            ("cancelled", "Canceled", "todo_cancel"),
            ("queued", "Queued", "todo"),
            ("not_started", "Not started", "todo"),
        ],
    )
    def test_each_task_keeps_status_and_navigation(self, status, label, image):
        state = TasksState(
            items=(
                self._item(status=status),
                self._item(title="Refactor mention dispatcher", status="completed", pr_url=None),
            ),
            has_any_tasks=True,
        )
        view = render_home_view(**self._kwargs(tasks_state=state))
        title, detail = self._task_items(view, expected_count=2)[0]
        assert title == "*Fix flaky retention test*"
        images = [
            element
            for block in view["blocks"]
            for element in block.get("elements", [])
            if element.get("type") == "image" and element.get("alt_text") == label
        ]
        assert any(element["image_url"].endswith(f"/slack_app/home/v1/{image}.png") for element in images)
        assert label in detail
        assert "posthog/posthog" in detail
        assert "<https://slack.com/archives/C1/p1234567890123456|Thread>" in detail
        assert "<https://app/project/1/tasks/abc|Open task>" in detail
        assert "<https://github.com/posthog/posthog/pull/123|View PR>" in detail
        assert "Updated 5m ago" in detail

    @pytest.mark.parametrize(
        "error_message,expected",
        [
            (None, None),
            ("", None),
            (" \n\t ", None),
            ("boom: timed out\nstack trace omitted", "boom: timed out stack trace omitted"),
        ],
    )
    def test_failed_task_keeps_nonempty_error_before_navigation(self, error_message, expected):
        state = TasksState(
            items=(self._item(status="failed", error_message=error_message),),
            has_any_tasks=True,
        )
        view = render_home_view(**self._kwargs(tasks_state=state))
        title, detail = self._task_items(view, expected_count=1)[0]
        assert title == "*Fix flaky retention test*"
        assert "Failed" in detail
        errors = [
            element["text"]
            for block in view["blocks"]
            if block["type"] == "context"
            for element in block["elements"]
            if element["type"] == "plain_text"
        ]
        assert errors == ([expected] if expected else [])
        if expected:
            assert detail.index(expected) < detail.index("Open task")
        assert "<https://github.com/posthog/posthog/pull/123|View PR>" in detail
        assert "<https://app/project/1/tasks/abc|Open task>" in detail

    def test_desktop_link_is_removed_without_losing_web_navigation(self):
        state = TasksState(items=(self._item(desktop_url="https://example.com/desktop/task/abc"),), has_any_tasks=True)
        view = render_home_view(**self._kwargs(tasks_state=state))
        _, detail = self._task_items(view, expected_count=1)[0]
        assert "<https://app/project/1/tasks/abc|Open task>" in detail
        assert "https://example.com/desktop/task/abc" not in _all_text(view)

    def test_only_the_desktop_link_is_withheld_from_a_viewer_without_desktop_access(self):
        # The task page enforces access itself, so the web link stays even when the
        # desktop one is withheld — the same rule the reply footer's links follow.
        state = TasksState(
            items=(self._item(desktop_url=None),),
            has_any_tasks=True,
            page=0,
            total_pages=1,
            total_filtered=1,
        )
        view = render_home_view(**self._kwargs(tasks_state=state))
        _, sub = self._task_items(view, expected_count=1)[0]

        assert "Open task" in sub
        assert "View on desktop" not in sub

    def test_title_is_plain_text_when_neither_thread_nor_task_link_is_available(self):
        # A row with no Slack permalink normally falls back to the task page. Withhold
        # that too and the title has nowhere to point, so it must not render a link.
        state = TasksState(
            items=(self._item(thread_url=None, posthog_url=None),),
            has_any_tasks=True,
            page=0,
            total_pages=1,
            total_filtered=1,
        )
        view = render_home_view(**self._kwargs(tasks_state=state))
        text = _all_text(view)

        assert "*Fix flaky retention test*" in text
        assert "|Fix flaky retention test>" not in text

    def test_task_with_no_repo_or_pr_skips_those_meta_parts(self):
        state = TasksState(
            items=(self._item(repository=None, pr_url=None),),
            has_any_tasks=True,
            page=0,
            total_pages=1,
            total_filtered=1,
        )
        view = render_home_view(**self._kwargs(tasks_state=state))
        _, sub = self._task_items(view, expected_count=1)[0]
        assert "posthog/posthog" not in sub
        assert "|View PR>" not in sub

    def test_repo_dropdown_renders_with_single_repo_and_includes_all_option(self):
        # Even with a single repo, the dropdown is always rendered so the
        # user has a visible "All repos" reset and can see the full repo
        # universe at a glance.
        state = TasksState(
            items=(self._item(),),
            available_repos=("posthog/posthog",),
            has_any_tasks=True,
            total_pages=1,
            total_filtered=1,
        )
        view = render_home_view(**self._kwargs(tasks_state=state))
        from products.slack_app.backend.services.slack_app_home import ACTION_TASKS_FILTER_REPO

        repo_select = next(
            el
            for b in view["blocks"]
            for el in b.get("elements", []) or []
            if el.get("action_id") == ACTION_TASKS_FILTER_REPO
        )
        labels = [o["text"]["text"] for o in repo_select["options"]]
        assert labels == ["All repos", "posthog/posthog"]

    def test_repo_dropdown_hidden_when_no_repos_available(self):
        state = TasksState(items=(self._item(repository=None),), has_any_tasks=True, total_pages=1, total_filtered=1)
        view = render_home_view(**self._kwargs(tasks_state=state))
        from products.slack_app.backend.services.slack_app_home import ACTION_TASKS_FILTER_REPO

        assert ACTION_TASKS_FILTER_REPO not in _action_ids(view)

    def test_empty_filter_result_shows_no_match_copy(self):
        state = TasksState(
            items=(),
            available_repos=("posthog/posthog",),
            selected_status="failed",
            has_any_tasks=True,
        )
        view = render_home_view(**self._kwargs(tasks_state=state))
        assert "No tasks match" in _all_text(view)
        # No task sections render when items is empty.
        sections = [
            b
            for b in view["blocks"]
            if b.get("type") == "section"
            and isinstance(b.get("text"), dict)
            and "https://app/project/" in b["text"].get("text", "")
        ]
        assert sections == []

    def test_pagination_buttons_render_with_target_pages(self):
        from products.slack_app.backend.services.slack_app_home import ACTION_TASKS_PAGE_NEXT, ACTION_TASKS_PAGE_PREV

        state = TasksState(
            items=(self._item(),),
            has_any_tasks=True,
            page=1,
            total_pages=3,
            total_filtered=42,
        )
        view = render_home_view(**self._kwargs(tasks_state=state))
        # Prev and Next sit side-by-side under distinct action_ids so Slack
        # doesn't reject the view for action_id collision.
        pagination = next(
            b
            for b in view["blocks"]
            if b.get("type") == "actions"
            and {el.get("action_id") for el in b["elements"]} == {ACTION_TASKS_PAGE_PREV, ACTION_TASKS_PAGE_NEXT}
        )
        by_action = {el["action_id"]: el for el in pagination["elements"]}
        assert by_action[ACTION_TASKS_PAGE_PREV]["value"] == "0"
        assert by_action[ACTION_TASKS_PAGE_NEXT]["value"] == "2"
        # Page indicator + result count render as a context block above.
        text = _all_text(view)
        assert "Page" in text and "2" in text and "of" in text and "3" in text
        assert "42 tasks" in text

    def test_pagination_hidden_when_only_one_page(self):
        state = TasksState(items=(self._item(),), has_any_tasks=True, page=0, total_pages=1, total_filtered=1)
        view = render_home_view(**self._kwargs(tasks_state=state))
        from products.slack_app.backend.services.slack_app_home import ACTION_TASKS_PAGE_NEXT, ACTION_TASKS_PAGE_PREV

        action_ids = _action_ids(view)
        assert ACTION_TASKS_PAGE_PREV not in action_ids
        assert ACTION_TASKS_PAGE_NEXT not in action_ids

    def test_refresh_button_in_controls_carries_current_page(self):
        from products.slack_app.backend.services.slack_app_home import ACTION_TASKS_REFRESH

        state = TasksState(items=(self._item(),), has_any_tasks=True, page=2, total_pages=3, total_filtered=42)
        view = render_home_view(**self._kwargs(tasks_state=state))
        controls = next(
            b
            for b in view["blocks"]
            if b.get("type") == "actions" and any(el.get("action_id") == ACTION_TASKS_REFRESH for el in b["elements"])
        )
        refresh_el = next(el for el in controls["elements"] if el["action_id"] == ACTION_TASKS_REFRESH)
        # Refresh keeps the current page so a click reloads the same view
        # rather than snapping back to 0.
        assert refresh_el["value"] == "2"


class TestRenderEditModal:
    def test_no_runtime_means_no_model_or_effort_blocks(self):
        view = render_edit_modal(current=AIPreferences())
        assert MODAL_BLOCK_RUNTIME_ADAPTER in _block_ids(view)
        assert _find_block(view, MODAL_BLOCK_MODEL) is None
        assert _find_block(view, MODAL_BLOCK_REASONING_EFFORT) is None

    def test_runtime_picked_unlocks_model_block(self):
        view = render_edit_modal(current=AIPreferences(runtime_adapter="claude"))
        assert _find_block(view, MODAL_BLOCK_MODEL) is not None
        # Effort block needs both the model and a non-empty supported list.
        assert _find_block(view, MODAL_BLOCK_REASONING_EFFORT) is None

    def test_model_block_id_is_scoped_to_the_runtime(self):
        # Slack replays a block's state across `views.update` when the block_id is
        # unchanged, so a model picked under the old runtime would survive a runtime
        # switch and get submitted. A per-runtime id makes it a new block instead.
        claude = render_edit_modal(current=AIPreferences(runtime_adapter="claude"))
        codex = render_edit_modal(current=AIPreferences(runtime_adapter="codex"))
        claude_block = _find_block(claude, MODAL_BLOCK_MODEL)
        codex_block = _find_block(codex, MODAL_BLOCK_MODEL)
        assert claude_block and codex_block
        assert claude_block["block_id"] != codex_block["block_id"]

    def test_model_options_match_runtime(self):
        view = render_edit_modal(current=AIPreferences(runtime_adapter="codex"))
        model_block = _find_block(view, MODAL_BLOCK_MODEL)
        assert model_block
        option_values = [o["value"] for o in model_block["element"]["options"]]
        # Codex models only — assert via prefix to stay resilient as the facade
        # adds new Codex ids.
        assert option_values
        assert all(v.startswith("gpt-") for v in option_values)

    def test_model_options_carry_the_cost_of_a_priced_model(self):
        view = render_edit_modal(current=AIPreferences(runtime_adapter="claude"))
        model_block = _find_block(view, MODAL_BLOCK_MODEL)
        assert model_block
        options = {o["value"]: o for o in model_block["element"]["options"]}
        assert "Claude Sonnet 5" in options["claude-opus-5"]["description"]["text"]
        assert "2.5×" in options["claude-opus-5"]["description"]["text"]

    def test_model_option_omits_the_cost_line_when_the_catalog_prices_nothing(self):
        view = render_edit_modal(current=AIPreferences(runtime_adapter="codex"))
        model_block = _find_block(view, MODAL_BLOCK_MODEL)
        assert model_block
        options = {o["value"]: o for o in model_block["element"]["options"]}
        assert "description" not in options["gpt-5"]

    def test_effort_block_renders_only_when_supported_efforts_provided(self):
        view = render_edit_modal(
            current=AIPreferences(runtime_adapter="claude", model="claude-opus-4-7"),
            supported_efforts=["low", "medium", "high"],
        )
        block = _find_block(view, MODAL_BLOCK_REASONING_EFFORT)
        assert block
        assert block["optional"] is True
        values = [o["value"] for o in block["element"]["options"]]
        assert values == ["low", "medium", "high"]

    def test_initial_options_reflect_current_values(self):
        view = render_edit_modal(
            current=AIPreferences(
                runtime_adapter="claude",
                model="claude-opus-4-7",
                reasoning_effort="high",
            ),
            supported_efforts=["low", "medium", "high"],
        )
        runtime_block = _find_block(view, MODAL_BLOCK_RUNTIME_ADAPTER)
        model_block = _find_block(view, MODAL_BLOCK_MODEL)
        effort_block = _find_block(view, MODAL_BLOCK_REASONING_EFFORT)
        assert runtime_block and model_block and effort_block
        assert runtime_block["element"]["initial_option"]["value"] == "claude"
        # Opus 4.7 is retired, so the picker lists it only because this preference is on it.
        # Leaving it out would show the modal with no model selected and save a different one.
        assert model_block["element"]["initial_option"]["value"] == "claude-opus-4-7"
        assert effort_block["element"]["initial_option"]["value"] == "high"
        # Slack rejects the whole view when an initial option is not one of the offered
        # options, down to the cost line under the name.
        assert model_block["element"]["initial_option"] in model_block["element"]["options"]

    def test_dispatch_action_set_on_runtime_and_model(self):
        view = render_edit_modal(current=AIPreferences(runtime_adapter="claude"))
        runtime_block = _find_block(view, MODAL_BLOCK_RUNTIME_ADAPTER)
        model_block = _find_block(view, MODAL_BLOCK_MODEL)
        assert runtime_block and model_block
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
# Handler tests — Tasks card controls
# ---------------------------------------------------------------------------


class TestTasksControlsRepublishTheList:
    """A click has to reach Slack as a different view, or the tab looks frozen.

    The rest of the Tasks coverage stops at a boundary — the renderer takes a
    hand-built `TasksState`, the decoding tests stop at the resolved view state. This
    joins them: a real `block_actions` payload in, the `views.publish` payload out.
    """

    def _seed(self, integration) -> None:
        # The card is scoped to the projects the clicker can reach, so U001 needs an identity.
        viewer = User.objects.create_and_join(integration.team.organization, "viewer@posthog.com", None)
        SlackUserProfileCache.objects.create(
            integration=integration,
            slack_user_id="U001",
            email=viewer.email,
        )
        # More than one page, so a Next click has somewhere to go.
        for index in range(12):
            task = Task.objects.create(
                team=integration.team,
                title=f"Task {index}",
                description="d",
                origin_product=Task.OriginProduct.SLACK,
                repository="posthog/posthog" if index % 2 == 0 else "posthog/other",
            )
            run = TaskRun.objects.create(task=task, team=integration.team, status=TaskRun.Status.IN_PROGRESS)
            SlackThreadTaskMapping.objects.create(
                team=integration.team,
                integration=integration,
                slack_workspace_id=SLACK_WORKSPACE_ID,
                channel="C1",
                thread_ts=f"170000000.{index:06d}",
                task=task,
                task_run=run,
                mentioning_slack_user_id="U001",
            )

    def _published_titles(self, view: dict) -> list[str]:
        return [
            block["text"]["text"].strip("*")
            for block in view["blocks"]
            if block["type"] == "section" and block.get("text", {}).get("text", "").startswith("*Task ")
        ]

    def test_next_publishes_a_different_page_and_the_filter_narrows_it(
        self, slack_integration, mock_slack_client, flag_on
    ):
        self._seed(slack_integration)

        with patch("products.slack_app.backend.services.slack_app_home.is_slack_workspace_admin", return_value=False):
            first = _tasks_click_payload(ACTION_TASKS_PAGE_NEXT, value="0")
            handle_ai_preferences_block_action(first, first["actions"][0])
            page_one = self._published_titles(mock_slack_client.views_publish.call_args.kwargs["view"])

            second = _tasks_click_payload(ACTION_TASKS_PAGE_NEXT, value="1")
            handle_ai_preferences_block_action(second, second["actions"][0])
            page_two = self._published_titles(mock_slack_client.views_publish.call_args.kwargs["view"])

            narrowed = _tasks_click_payload(ACTION_TASKS_FILTER_REPO, repo="posthog/other")
            handle_ai_preferences_block_action(narrowed, narrowed["actions"][0])
            filtered = self._published_titles(mock_slack_client.views_publish.call_args.kwargs["view"])

        assert len(page_one) == 10
        assert page_two and not set(page_two) & set(page_one)
        # Odd indices carry posthog/other, so the filter must leave only those.
        assert filtered and all(int(title.split()[1]) % 2 == 1 for title in filtered)


class TestTasksControlsResolveViewState:
    """What the Tasks controls ask the resolver for, without touching the database.

    The Home tab holds no server-side state: the page rides on the clicked button's
    `value` and the filters ride on the view's input state. These lock that decoding,
    which is otherwise only observable through a full publish.
    """

    def _resolved_state(self, monkeypatch, payload: dict):
        captured: dict[str, Any] = {}
        monkeypatch.setattr(slack_app_home, "_resolve_interaction_integration", lambda team_id, user_id: object())
        monkeypatch.setattr(
            slack_app_home,
            "_republish_home",
            lambda integration, slack_user_id, *, view_state=None: captured.update(state=view_state),
        )
        handle_ai_preferences_block_action(payload, payload["actions"][0])
        assert "state" in captured, "the click never reached a republish"
        return captured["state"]

    @pytest.mark.parametrize(
        "action_id,value,expected_page",
        [
            (ACTION_TASKS_PAGE_NEXT, "1", 1),
            (ACTION_TASKS_PAGE_PREV, "0", 0),
            (ACTION_TASKS_PAGE_NEXT, "7", 7),
            # A button that somehow arrives without a usable page falls back to the first.
            (ACTION_TASKS_PAGE_NEXT, None, 0),
            (ACTION_TASKS_PAGE_NEXT, "not-a-number", 0),
        ],
    )
    def test_page_comes_off_the_clicked_button(self, monkeypatch, action_id, value, expected_page):
        state = self._resolved_state(monkeypatch, _tasks_click_payload(action_id, value=value))
        assert state.tasks_page == expected_page

    def test_paging_keeps_the_active_repo_filter(self, monkeypatch):
        # Paging must not silently widen the list back to every repo.
        state = self._resolved_state(
            monkeypatch, _tasks_click_payload(ACTION_TASKS_PAGE_NEXT, value="1", repo="posthog/posthog")
        )
        assert (state.selected_repo, state.tasks_page) == ("posthog/posthog", 1)

    def test_changing_the_filter_returns_to_the_first_page(self, monkeypatch):
        # Otherwise a narrower result set leaves the viewer stranded past its last page.
        state = self._resolved_state(
            monkeypatch, _tasks_click_payload(ACTION_TASKS_FILTER_REPO, repo="posthog/posthog")
        )
        assert (state.selected_repo, state.tasks_page) == ("posthog/posthog", 0)


# ---------------------------------------------------------------------------
# Handler tests — app_home_opened event
# ---------------------------------------------------------------------------


class TestHandleAppHomeOpened:
    def test_publishes_view_for_known_user(self, slack_integration, mock_slack_client, flag_on, admin_user):
        handle_app_home_opened({"user": "U001"}, SLACK_WORKSPACE_ID, integration=slack_integration)
        assert mock_slack_client.views_publish.called
        kwargs = mock_slack_client.views_publish.call_args.kwargs
        assert kwargs["user_id"] == "U001"
        assert kwargs["view"]["type"] == "home"

    def test_noop_when_user_missing(self, slack_integration, mock_slack_client, flag_on):
        handle_app_home_opened({}, SLACK_WORKSPACE_ID, integration=slack_integration)
        assert not mock_slack_client.views_publish.called

    def test_home_opened_is_attributed_to_the_resolved_posthog_user(
        self, slack_integration, mock_slack_client, flag_on, admin_user
    ):
        opener = User.objects.create_and_join(slack_integration.team.organization, "opener@posthog.com", None)
        SlackUserProfileCache.objects.create(integration=slack_integration, slack_user_id="U001", email=opener.email)

        with patch("products.slack_app.backend.services.slack_app_home.capture_slack_event") as mock_capture:
            handle_app_home_opened({"user": "U001"}, SLACK_WORKSPACE_ID, integration=slack_integration)

        assert mock_capture.call_args.args[1] == "slack app home opened"
        assert mock_capture.call_args.kwargs["posthog_user"] == opener

    @pytest.mark.parametrize("viewer_linked", [True, False])
    def test_multiplayer_section_shows_only_to_a_linked_viewer(
        self, slack_integration, mock_slack_client, flag_on, admin_user, viewer_linked
    ):
        if viewer_linked:
            opener = User.objects.create_and_join(slack_integration.team.organization, "opener@posthog.com", None)
            SlackUserProfileCache.objects.create(
                integration=slack_integration, slack_user_id="U001", email=opener.email
            )

        handle_app_home_opened({"user": "U001"}, SLACK_WORKSPACE_ID, integration=slack_integration)

        view = mock_slack_client.views_publish.call_args.kwargs["view"]
        assert (ACTION_SET_THREAD_JOIN_MODE in _action_ids(view)) is viewer_linked
        assert (ACTION_SET_THREAD_JOIN_MODE in _action_ids(view)) is viewer_linked

    def test_join_picker_shows_without_the_plan_card(self, slack_integration, mock_slack_client, flag_on, admin_user):
        # Who may join a thread is not a plan feature, so closing the BYOS gate must not hide it.
        opener = User.objects.create_and_join(slack_integration.team.organization, "opener@posthog.com", None)
        SlackUserProfileCache.objects.create(integration=slack_integration, slack_user_id="U001", email=opener.email)

        with patch("products.slack_app.backend.services.slack_app_home.is_slack_app_byos_enabled", return_value=False):
            handle_app_home_opened({"user": "U001"}, SLACK_WORKSPACE_ID, integration=slack_integration)

        view = mock_slack_client.views_publish.call_args.kwargs["view"]
        assert ACTION_SET_THREAD_JOIN_MODE in _action_ids(view)
        assert "ChatGPT plan" not in _all_text(view)

    def _github_row(self, user: User, login: str) -> UserIntegration:
        return UserIntegration.objects.create(
            user=user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id=f"install-{login}",
            config={"github_user": {"login": login}, "account": {"name": login}},
            sensitive_config={"user_access_token": "gho_x", "user_refresh_token": "ghr_x"},
        )

    def test_github_card_lists_only_the_opening_users_installations(
        self, slack_integration, mock_slack_client, flag_on, admin_user
    ):
        organization = slack_integration.team.organization
        opener = User.objects.create_and_join(organization, "opener@posthog.com", None)
        colleague = User.objects.create_and_join(organization, "colleague@posthog.com", None)
        self._github_row(opener, "opener-gh")
        self._github_row(colleague, "colleague-gh")
        SlackUserProfileCache.objects.create(
            integration=slack_integration,
            slack_user_id="U001",
            email=opener.email,
        )

        handle_app_home_opened({"user": "U001"}, SLACK_WORKSPACE_ID, integration=slack_integration)

        text = _all_text(mock_slack_client.views_publish.call_args.kwargs["view"])
        assert "opener-gh" in text
        assert "colleague-gh" not in text

    @pytest.mark.parametrize(
        "viewer_email, is_member, reaches_project",
        [
            (None, False, False),
            ("outsider@example.com", False, False),
            ("member@posthog.com", True, True),
        ],
        ids=["viewer_we_cannot_identify", "viewer_outside_every_connected_org", "organization_member"],
    )
    def test_only_an_organization_member_reaches_the_connected_project(
        self, slack_integration, mock_slack_client, flag_on, admin_user, viewer_email, is_member, reaches_project
    ):
        slack_integration.team.name = "Zephyr Analytics"
        slack_integration.team.save(update_fields=["name"])
        if is_member:
            User.objects.create_and_join(slack_integration.team.organization, viewer_email, None)
        if viewer_email:
            SlackUserProfileCache.objects.create(
                integration=slack_integration,
                slack_user_id="U001",
                email=viewer_email,
            )

        handle_app_home_opened({"user": "U001"}, SLACK_WORKSPACE_ID, integration=slack_integration)

        text = _all_text(mock_slack_client.views_publish.call_args.kwargs["view"])
        assert ("Zephyr Analytics" in text) is reaches_project
        assert ("No project to show yet" in text) is not reaches_project

    def test_deactivated_user_is_not_resolved_from_their_slack_identity(
        self, slack_integration, mock_slack_client, flag_on, admin_user
    ):
        organization = slack_integration.team.organization
        offboarded = User.objects.create_and_join(organization, "offboarded@posthog.com", None)
        self._github_row(offboarded, "offboarded-gh")
        SlackUserProfileCache.objects.create(
            integration=slack_integration,
            slack_user_id="U001",
            email=offboarded.email,
        )
        offboarded.is_active = False
        offboarded.save(update_fields=["is_active"])

        handle_app_home_opened({"user": "U001"}, SLACK_WORKSPACE_ID, integration=slack_integration)

        text = _all_text(mock_slack_client.views_publish.call_args.kwargs["view"])
        assert "offboarded-gh" not in text
        assert "No project to show yet" in text


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


class TestResetPersonal:
    def test_mapped_viewer_reset_clears_central_config(self, slack_integration, mock_slack_client, flag_on):
        user = User.objects.create_and_join(slack_integration.team.organization, "mapped@example.com", None)
        SlackUserProfileCache.objects.create(
            integration=slack_integration, slack_user_id="U001", email="mapped@example.com"
        )
        update_user_ai_run_preferences(
            slack_integration.team_id, user.id, runtime_adapter="codex", model="gpt-5.5", reasoning_effort=None
        )
        payload = _block_action_payload(
            action_id=ACTION_RESET_PERSONAL,
            slack_user_id="U001",
            trigger_id="trig.8",
        )
        handle_ai_preferences_block_action(payload, payload["actions"][0])

        assert get_user_ai_run_preferences(slack_integration.team_id, user.id) == {}
        assert mock_slack_client.views_publish.called


class TestResetProjectPersonal:
    @pytest.mark.parametrize(
        "other_settings",
        [
            {"untagged_followup_mode": UntaggedFollowupMode.AUTO},
            {"untagged_question_mode": UntaggedFollowupMode.NEVER},
            {"auto_model_choice": True},
        ],
        ids=["followup_mode", "question_mode", "auto_model_choice"],
    )
    def test_clears_routing_only_when_other_settings_present(
        self, slack_integration, mock_slack_client, flag_on, admin_user, other_settings
    ):
        # Mixed row → reset clears routing, the other setting stays.
        SlackSettings.objects.create(
            default_integration=slack_integration,
            slack_workspace_id=SLACK_WORKSPACE_ID,
            slack_user_id="U001",
            **other_settings,
        )
        payload = _block_action_payload(
            action_id=ACTION_RESET_PROJECT_PERSONAL,
            slack_user_id="U001",
            trigger_id="trig.5",
        )
        handle_ai_preferences_block_action(payload, payload["actions"][0])

        row = SlackSettings.objects.get(slack_workspace_id=SLACK_WORKSPACE_ID, slack_user_id="U001")
        assert row.default_integration_id is None
        assert {field: getattr(row, field) for field in other_settings} == other_settings
        assert mock_slack_client.views_publish.called

    def test_deletes_row_when_no_other_settings_remain(self, slack_integration, mock_slack_client, flag_on, admin_user):
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


class TestSetProjectWorkspace:
    """The workspace default is one setting for everyone in the Slack workspace.

    Slack's admin flag gates the control upstream and says nothing about PostHog, so
    these cover the second gate: the clicker must reach the project they picked. Every
    case arrives as a `block_actions` payload, which is what a view Slack published
    before access was removed replays.
    """

    def _click(self, slack_user_id: str, team_id: int) -> dict:
        return _block_action_payload(
            action_id=ACTION_SET_PROJECT_WORKSPACE,
            slack_user_id=slack_user_id,
            selected_value=str(team_id),
        )

    def test_slack_admin_with_no_posthog_account_cannot_set_the_default(
        self, slack_integration, mock_slack_client, flag_on, admin_user
    ):
        payload = self._click("U001", slack_integration.team_id)

        handle_ai_preferences_block_action(payload, payload["actions"][0])

        assert not SlackSettings.objects.filter(slack_workspace_id=SLACK_WORKSPACE_ID, slack_user_id=None).exists()

    def test_slack_admin_who_is_an_organization_member_sets_the_default(
        self, slack_integration, mock_slack_client, flag_on, admin_user
    ):
        member = User.objects.create_and_join(slack_integration.team.organization, "admin@posthog.com", None)
        SlackUserProfileCache.objects.create(integration=slack_integration, slack_user_id="U001", email=member.email)
        payload = self._click("U001", slack_integration.team_id)

        handle_ai_preferences_block_action(payload, payload["actions"][0])

        row = SlackSettings.objects.get(slack_workspace_id=SLACK_WORKSPACE_ID, slack_user_id=None)
        assert row.default_integration_id == slack_integration.id

    def test_member_of_one_connected_organization_cannot_pick_another_ones_project(
        self, slack_integration, mock_slack_client, flag_on, admin_user
    ):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_integration = Integration.objects.create(
            team=other_team,
            kind="slack",
            integration_id=SLACK_WORKSPACE_ID,
            sensitive_config={"access_token": "xoxb"},
        )
        member = User.objects.create_and_join(slack_integration.team.organization, "admin@posthog.com", None)
        SlackUserProfileCache.objects.create(integration=slack_integration, slack_user_id="U001", email=member.email)
        payload = self._click("U001", other_integration.team_id)

        handle_ai_preferences_block_action(payload, payload["actions"][0])

        assert not SlackSettings.objects.filter(slack_workspace_id=SLACK_WORKSPACE_ID, slack_user_id=None).exists()


# ---------------------------------------------------------------------------
# Handler tests — view_submission
# ---------------------------------------------------------------------------


class TestPersonalSubmit:
    def test_unmapped_viewer_submit_is_refused_with_a_link_prompt(
        self, slack_integration, mock_slack_client, flag_on, admin_user
    ):
        # No PostHog user maps to U001, so there is nowhere to store the
        # preference — the modal must say so instead of writing a Slack pin.
        payload = _view_submission_payload(
            callback_id=EDIT_MODAL_PERSONAL_CALLBACK_ID,
            slack_user_id="U001",
            runtime_adapter="claude",
            model="claude-opus-4-7",
            effort="high",
        )
        response = handle_app_home_view_submission(payload)
        body = json.loads(response.content)
        assert body["response_action"] == "errors"
        assert "Link your PostHog account" in str(body["errors"])
        assert not SlackSettings.objects.filter(slack_user_id="U001").exists()

    def test_multi_project_viewer_without_a_routing_default_is_asked_to_pick(
        self, slack_integration, mock_slack_client, flag_on
    ):
        # Two accessible projects and no routing default must not silently save
        # against the oldest install; the mention path refuses in the same state.
        organization = slack_integration.team.organization
        team_b = Team.objects.create(organization=organization, name="B")
        Integration.objects.create(
            team=team_b, kind="slack", integration_id=SLACK_WORKSPACE_ID, sensitive_config={"access_token": "x"}
        )
        User.objects.create_and_join(organization, "mapped@example.com", None)
        for i in Integration.objects.filter(integration_id=SLACK_WORKSPACE_ID):
            SlackUserProfileCache.objects.create(integration=i, slack_user_id="U001", email="mapped@example.com")

        payload = _view_submission_payload(
            callback_id=EDIT_MODAL_PERSONAL_CALLBACK_ID,
            slack_user_id="U001",
            runtime_adapter="claude",
            model="claude-opus-4-7",
            effort="high",
        )
        response = handle_app_home_view_submission(payload)
        body = json.loads(response.content)
        assert body["response_action"] == "errors"
        assert "Pick a default project" in str(body["errors"])

    def test_save_targets_the_viewers_accessible_project_not_the_oldest_install(
        self, slack_integration, mock_slack_client, flag_on
    ):
        # The workspace's oldest install (the fixture's) belongs to an org the
        # viewer isn't in; the save must land on their own project rather than
        # falling open to the oldest one.
        foreign = slack_integration
        own_org = Organization.objects.create(name="Mine")
        own = Integration.objects.create(
            team=Team.objects.create(organization=own_org, name="Mine team"),
            kind="slack",
            integration_id=SLACK_WORKSPACE_ID,
            sensitive_config={"access_token": "x"},
        )
        user = User.objects.create_and_join(own_org, "mapped@example.com", None)
        for i in (foreign, own):
            SlackUserProfileCache.objects.create(integration=i, slack_user_id="U001", email="mapped@example.com")

        payload = _view_submission_payload(
            callback_id=EDIT_MODAL_PERSONAL_CALLBACK_ID,
            slack_user_id="U001",
            runtime_adapter="claude",
            model="claude-opus-4-7",
            effort="high",
        )
        response = handle_app_home_view_submission(payload)
        assert json.loads(response.content) == {"response_action": "clear"}
        assert get_user_ai_run_preferences(own.team_id, user.id).get("model") == "claude-opus-4-7"
        assert get_user_ai_run_preferences(foreign.team_id, user.id) == {}

    def test_gated_model_is_rejected_at_save(self, slack_integration, mock_slack_client, flag_on):
        user = User.objects.create_and_join(slack_integration.team.organization, "mapped@example.com", None)
        SlackUserProfileCache.objects.create(
            integration=slack_integration, slack_user_id="U001", email="mapped@example.com"
        )
        payload = _view_submission_payload(
            callback_id=EDIT_MODAL_PERSONAL_CALLBACK_ID,
            slack_user_id="U001",
            runtime_adapter="claude",
            model="claude-opus-4-7",
            effort="high",
        )
        with patch(
            "products.tasks.backend.facade.run_config.get_model_access_error",
            return_value="This model is not available on your account.",
        ):
            response = handle_app_home_view_submission(payload)
        body = json.loads(response.content)
        assert body["response_action"] == "errors"
        assert "not available" in str(body["errors"])
        assert get_user_ai_run_preferences(slack_integration.team_id, user.id) == {}

    def test_mapped_viewer_submit_writes_central_config(self, slack_integration, mock_slack_client, flag_on):
        user = User.objects.create_and_join(slack_integration.team.organization, "mapped@example.com", None)
        SlackUserProfileCache.objects.create(
            integration=slack_integration, slack_user_id="U001", email="mapped@example.com"
        )
        payload = _view_submission_payload(
            callback_id=EDIT_MODAL_PERSONAL_CALLBACK_ID,
            slack_user_id="U001",
            runtime_adapter="claude",
            model="claude-opus-4-7",
            effort="high",
        )
        response = handle_app_home_view_submission(payload)
        assert json.loads(response.content) == {"response_action": "clear"}

        stored = get_user_ai_run_preferences(slack_integration.team_id, user.id)
        assert stored.get("model") == "claude-opus-4-7"
        assert stored.get("runtime_adapter") == "claude"

    @pytest.mark.parametrize(
        "runtime_adapter,model,effort",
        [
            # `max` isn't supported on claude-sonnet-4-6.
            pytest.param("claude", "claude-sonnet-4-6", "max", id="unsupported-effort"),
            # A model owned by the other runtime.
            pytest.param("claude", "gpt-5.5", None, id="cross-runtime-model"),
        ],
    )
    def test_invalid_triple_keeps_modal_open_with_error(
        self, slack_integration, mock_slack_client, flag_on, runtime_adapter, model, effort
    ):
        # A mapped viewer, so the request reaches the central config write —
        # whose validation is what rejects the triple.
        user = User.objects.create_and_join(slack_integration.team.organization, "mapped@example.com", None)
        SlackUserProfileCache.objects.create(
            integration=slack_integration, slack_user_id="U001", email="mapped@example.com"
        )
        payload = _view_submission_payload(
            callback_id=EDIT_MODAL_PERSONAL_CALLBACK_ID,
            slack_user_id="U001",
            runtime_adapter=runtime_adapter,
            model=model,
            effort=effort,
        )
        response = handle_app_home_view_submission(payload)
        body = json.loads(response.content)
        assert body["response_action"] == "errors"
        assert MODAL_BLOCK_RUNTIME_ADAPTER in body["errors"]
        # Modal left open: nothing stored.
        assert get_user_ai_run_preferences(slack_integration.team_id, user.id) == {}


class TestModalRerender:
    def test_switching_runtime_drops_the_other_runtime_model(self, slack_integration, mock_slack_client, flag_on):
        # Runtime just flipped to Claude; Slack still reports the Codex model and its
        # effort in view state. Both have to be gone from the re-rendered modal.
        state = _modal_state(runtime_adapter="codex", model="gpt-5", effort="high")
        state[MODAL_BLOCK_RUNTIME_ADAPTER] = {MODAL_ACTION_RUNTIME_ADAPTER: {"selected_option": {"value": "claude"}}}
        payload: dict[str, Any] = {
            "type": "block_actions",
            "team": {"id": SLACK_WORKSPACE_ID},
            "user": {"id": "U001"},
            "actions": [{"action_id": MODAL_ACTION_RUNTIME_ADAPTER}],
            "view": {
                "id": "V1",
                "hash": "H1",
                "callback_id": EDIT_MODAL_PERSONAL_CALLBACK_ID,
                "state": {"values": state},
            },
        }
        handle_ai_preferences_block_action(payload, payload["actions"][0])

        view = mock_slack_client.views_update.call_args.kwargs["view"]
        model_block = _find_block(view, MODAL_BLOCK_MODEL)
        assert model_block
        # A block id Slack has no state for, and nothing preselected in it.
        assert model_block["block_id"] == f"{MODAL_BLOCK_MODEL}:claude"
        assert "initial_option" not in model_block["element"]
        assert _find_block(view, MODAL_BLOCK_REASONING_EFFORT) is None


class TestRetiredWorkspaceModal:
    def test_stale_workspace_submission_is_ignored(self, slack_integration, mock_slack_client, flag_on, admin_user):
        # A workspace modal opened before this callback id was retired can still
        # be submitted afterwards. It must not write a workspace-wide row.
        payload = _view_submission_payload(
            callback_id="slack_app_ai_prefs:workspace",
            slack_user_id="U001",
            runtime_adapter="claude",
            model="claude-opus-4-7",
            effort="high",
        )
        response = handle_app_home_view_submission(payload)
        assert response.status_code == 200
        assert not SlackSettings.objects.exists()


class TestInteractionResolvesTheViewersIntegration:
    """A workspace connected to two organizations must answer clicks for the right one.

    Everything the tab is keyed on hangs off the resolved integration — the rollout flag
    is scoped to an organization, and the task list, project card and account link are all
    scoped to its team. Answering a click against an arbitrary row of the workspace makes
    the tab disagree with itself, which reads as a control that does nothing.
    """

    def _second_org_integration(self) -> Integration:
        organization = Organization.objects.create(name="Other Org")
        team = Team.objects.create(organization=organization, name="Other Team")
        return Integration.objects.create(
            team=team,
            kind="slack",
            integration_id=SLACK_WORKSPACE_ID,
            sensitive_config={"access_token": "xoxb-other"},
        )

    # Personal pick and workspace default are separate rungs of the ladder; both must beat
    # row order, since `slack_integration` is created first and any unordered lookup wins with it.
    @pytest.mark.parametrize("pick_owner", ["U001", None])
    def test_the_saved_project_pick_beats_row_order(self, slack_integration, pick_owner):
        preferred = self._second_org_integration()
        SlackSettings.objects.create(
            slack_workspace_id=SLACK_WORKSPACE_ID,
            slack_user_id=pick_owner,
            default_integration=preferred,
        )

        resolved = slack_app_home._resolve_interaction_integration(SLACK_WORKSPACE_ID, "U001")

        assert resolved is not None and resolved.id == preferred.id

    def test_unknown_workspace_resolves_to_nothing(self, db):
        assert slack_app_home._resolve_interaction_integration("T_NOT_CONNECTED", "U001") is None

    def test_no_pick_falls_back_to_the_same_install_regardless_of_candidate_order(self, slack_integration):
        # The auth filter hands back candidates freshest-verdict-first, so the fallback
        # can't take the front of that list and stay put across cache expiries.
        newer = self._second_org_integration()
        oldest = min(slack_integration.id, newer.id)

        first = slack_app_home._resolve_interaction_integration(SLACK_WORKSPACE_ID, "U001")
        with patch(
            "products.slack_app.backend.services.slack_auth.check_integrations_auth_and_filter",
            side_effect=lambda candidates, **_: list(reversed(candidates)),
        ):
            reordered = slack_app_home._resolve_interaction_integration(SLACK_WORKSPACE_ID, "U001")

        assert first is not None and reordered is not None
        assert first.id == reordered.id == oldest


class TestNoProjectAccessCard:
    """What someone sees when no PostHog project connected here is visible to them.

    Without this the tab draws its normal cards against nothing: no project picker, and a
    Tasks card inviting them to mention @PostHog — which won't run either, for the same
    reason. The regression to catch is a card reappearing in that state.
    """

    def _view(self, **overrides) -> dict:
        kwargs: dict[str, Any] = {
            "is_admin": True,
            "has_project_access": False,
            "tasks_state": TasksState(),
            "stats_state": StatsState(tasks_started=4),
            "account_state": AccountState(enabled=True, link_url="https://app/link"),
            "project_state": ProjectState(candidates=(ProjectChoice(team_id=1, label="Org · Team"),)),
        }
        kwargs.update(overrides)
        return render_home_view(**kwargs)

    @staticmethod
    def _urls(view: dict) -> list[str]:
        return [
            element["url"]
            for block in view["blocks"]
            for element in block.get("elements", []) or []
            if "url" in element
        ]

    def test_explains_the_dead_end_and_links_to_the_settings_page(self):
        view = self._view()

        assert "No project to show yet" in _all_text(view)
        assert "ask an admin" in _all_text(view)
        assert self._urls(view) == ["http://localhost:8010/settings/project-integrations"]

    def test_names_the_address_mismatch_and_routes_it_to_personal_integrations(self):
        personal = "http://localhost:8010/project/7/settings/user-personal-integrations"
        view = self._view(account_settings_url=personal)

        assert "same email address as your Slack profile" in _all_text(view)
        assert personal in self._urls(view)

    def test_withholds_the_signed_account_link_from_a_viewer_who_was_not_identified(self):
        # The URL is in `account_state` on this path, so its absence has to be asserted.
        view = self._view(account_settings_url="http://localhost:8010/project/7/settings/user-personal-integrations")

        assert "https://app/link" not in json.dumps(view)

    def test_suppresses_every_card_that_needs_a_project(self):
        # Each of these would otherwise render from the states passed above.
        text = _all_text(self._view())

        assert "🦔 Tasks" not in text
        assert "Workspace activity" not in text
        assert "Project routing" not in text
        assert not _action_ids(self._view())

    def test_normal_tab_is_untouched_when_a_project_is_reachable(self):
        assert "No project to show yet" not in _all_text(self._view(has_project_access=True))


class TestUnidentifiedViewerProjectList:
    """What the tab lists for a Slack user it cannot map to a PostHog account.

    The regression to catch is the list widening again. A Slack workspace can connect
    several organizations, so reaching any candidate publishes the project and
    organization names of orgs the viewer is not a member of to anyone in the workspace.
    """

    @pytest.fixture(autouse=True)
    def setup(self, db):
        from posthog.models.integration import Integration
        from posthog.models.organization import Organization
        from posthog.models.team.team import Team

        self.own_org = Organization.objects.create(name="Acme")
        self.other_org = Organization.objects.create(name="Umbrella")
        self.rendered_for = Integration.objects.create(
            team=Team.objects.create(organization=self.own_org, name="Acme prod"),
            kind="slack",
            integration_id="T_WS",
            sensitive_config={"access_token": "xoxb"},
        )
        self.other_org_install = Integration.objects.create(
            team=Team.objects.create(organization=self.other_org, name="Umbrella prod"),
            kind="slack",
            integration_id="T_WS",
            sensitive_config={"access_token": "xoxb"},
        )

    def test_reaches_no_project_at_all(self):
        from products.slack_app.backend.services.slack_app_home import _filter_accessible_integrations

        # No SlackUserProfileCache row and no OAuth link, so the viewer is unidentifiable.
        accessible = _filter_accessible_integrations(
            self.rendered_for, "U_STRANGER", [self.rendered_for, self.other_org_install]
        )

        assert accessible == []
