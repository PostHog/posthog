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
from types import ModuleType
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.models import (
    SlackSettings,
    SlackThreadTaskMapping,
    SlackUserProfileCache,
    UntaggedFollowupMode,
)
from products.slack_app.backend.services import slack_app_home
from products.slack_app.backend.services.slack_app_home import (
    ACTION_EDIT_PERSONAL,
    ACTION_RESET_PERSONAL,
    ACTION_RESET_PROJECT_PERSONAL,
    ACTION_SET_UNTAGGED_FOLLOWUP_MODE,
    ACTION_TASKS_FILTER_REPO,
    ACTION_TASKS_PAGE_NEXT,
    ACTION_TASKS_PAGE_PREV,
    ACTION_UNLINK_ACCOUNT,
    BLOCK_TASKS_CONTROLS,
    EDIT_MODAL_PERSONAL_CALLBACK_ID,
    HOME_ACTION_IDS,
    MODAL_ACTION_MODEL,
    MODAL_ACTION_REASONING_EFFORT,
    MODAL_ACTION_RUNTIME_ADAPTER,
    MODAL_BLOCK_MODEL,
    MODAL_BLOCK_REASONING_EFFORT,
    MODAL_BLOCK_RUNTIME_ADAPTER,
    AccountState,
    GitHubAccount,
    GitHubState,
    PreferenceSource,
    ProjectChoice,
    ProjectState,
    StatsState,
    TaskItem,
    TasksState,
    handle_ai_preferences_block_action,
    handle_app_home_opened,
    handle_app_home_view_submission,
    parse_modal_submission,
    render_edit_modal,
    render_home_view,
    resolve_source,
)
from products.slack_app.backend.services.slack_settings import AIPreferences
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


@dataclass
class _Row:
    """Duck-type stand-in for a SlackSettings row — keeps the renderer tests
    off the database. Declared at module scope (instead of inside the helper
    below) so mypy can resolve the dataclass-generated attribute types."""

    runtime_adapter: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None


def _make_row(
    *,
    runtime_adapter: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> Any:
    # Returned as Any so call sites that pass this to render_home_view /
    # resolve_source (which expect a real `SlackSettings`) don't trip mypy.
    return _Row(runtime_adapter=runtime_adapter, model=model, reasoning_effort=reasoning_effort)


def _action_ids(view: dict) -> list[str]:
    out: list[str] = []
    for block in view["blocks"]:
        for el in block.get("elements", []) or []:
            if "action_id" in el:
                out.append(el["action_id"])
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
) -> dict:
    return {
        "type": "block_actions",
        "team": {"id": SLACK_WORKSPACE_ID},
        "user": {"id": slack_user_id},
        "trigger_id": trigger_id,
        "channel": {"id": channel} if channel else None,
        "actions": [{"action_id": action_id}],
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
        view = render_home_view(
            effective=AIPreferences(),
            user_row=None,
            is_admin=is_admin,
        )
        assert view["type"] == "home"
        ids = _action_ids(view)
        # Personal edit always present; reset hidden when no override. Admins get
        # no extra model control — the model is purely a personal preference.
        assert ACTION_EDIT_PERSONAL in ids
        assert ACTION_RESET_PERSONAL not in ids

    def test_personal_override_renders_reset_button(self):
        view = render_home_view(
            effective=AIPreferences(runtime_adapter="claude", model="claude-opus-4-7", reasoning_effort="high"),
            user_row=_make_row(runtime_adapter="claude", model="claude-opus-4-7", reasoning_effort="high"),
            is_admin=False,
        )
        assert ACTION_RESET_PERSONAL in _action_ids(view)

    def test_active_model_summary_mentions_model_label(self):
        view = render_home_view(
            effective=AIPreferences(runtime_adapter="claude", model="claude-opus-4-7", reasoning_effort="high"),
            user_row=_make_row(runtime_adapter="claude", model="claude-opus-4-7", reasoning_effort="high"),
            is_admin=True,
        )
        text_blob = " ".join(block["text"]["text"] for block in view["blocks"] if block.get("type") == "section")
        # Friendly label rather than raw model id; source attribution visible.
        assert "Claude Opus 4.7" in text_blob
        assert "Your personal override" in _all_text(view)

    def test_every_control_the_tab_renders_is_routable(self):
        # The interactivity endpoint claims region ownership and dispatches off
        # HOME_ACTION_IDS, so a control missing from it renders as a button that
        # silently does nothing. Render every card at once and check the whole set.
        view = render_home_view(
            effective=AIPreferences(runtime_adapter="claude", model="claude-opus-4-7"),
            user_row=_make_row(runtime_adapter="claude", model="claude-opus-4-7"),
            is_admin=True,
            account_state=AccountState(enabled=True, link_url="https://app/link"),
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
        )

        # Equality both ways: an unroutable control fails on the left, and a card that
        # stopped rendering fails on the right instead of passing a subset check trivially.
        # Unlink only renders once an account is linked, which this fixture deliberately isn't.
        assert set(_action_ids(view)) == HOME_ACTION_IDS - {ACTION_UNLINK_ACCOUNT}

    def test_source_resolution_is_atomic(self):
        # A user row missing half the pair isn't a real override.
        assert resolve_source(_make_row(reasoning_effort="medium")) == PreferenceSource.unset()
        assert resolve_source(None) == PreferenceSource.unset()
        assert (
            resolve_source(_make_row(runtime_adapter="claude", model="claude-opus-4-7")) == PreferenceSource.personal()
        )


class TestThreadFollowupsCard:
    def _view(self, mode) -> dict:
        return render_home_view(
            effective=AIPreferences(),
            user_row=None,
            is_admin=False,
            untagged_followup_mode=mode,
        )

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
            el
            for block in view["blocks"]
            for el in block.get("elements", []) or []
            if el.get("action_id") == ACTION_SET_UNTAGGED_FOLLOWUP_MODE
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


class TestLinkedAccountsCard:
    def _view(self, *, account_state=None, github_state=None) -> dict:
        return render_home_view(
            effective=AIPreferences(),
            user_row=None,
            is_admin=False,
            account_state=account_state,
            github_state=github_state,
        )

    def _rows(self, view: dict) -> list[tuple[str, dict | None]]:
        return [
            (block["text"]["text"], block.get("accessory"))
            for block in view["blocks"]
            if block.get("type") == "section" and block["text"]["text"].startswith(("*PostHog*", "*GitHub*"))
        ]

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
            assert ("✅" in text) is credentials_usable

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
            "effective": AIPreferences(),
            "user_row": None,
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
        """Return per-task (title_text, sub_text) tuples.

        Each task renders as a section (title) immediately followed by a
        context block carrying the error/meta rows. Sub-text is "" when the
        task has no meta — happens only in tests that pass an empty TaskItem.
        """
        items: list[tuple[str, str]] = []
        blocks = view["blocks"]
        for index, block in enumerate(blocks):
            if (
                block.get("type") == "section"
                and isinstance(block.get("text"), dict)
                and "|Fix flaky retention test>" in block["text"].get("text", "")
                or block.get("type") == "section"
                and "|Refactor mention dispatcher>" in block.get("text", {}).get("text", "")
            ):
                title = block["text"]["text"]
                neighbour = blocks[index + 1] if index + 1 < len(blocks) else None
                sub = ""
                if neighbour and neighbour.get("type") == "context":
                    sub = neighbour["elements"][0]["text"]
                items.append((title, sub))
        assert len(items) == expected_count, f"expected {expected_count} task items, found {len(items)}"
        return items

    def test_card_hidden_when_state_is_none(self):
        view = render_home_view(**self._kwargs())
        assert "Tasks" not in _all_text(view)

    def test_first_use_state_invites_user_to_mention(self):
        view = render_home_view(**self._kwargs(tasks_state=TasksState()))
        text = _all_text(view)
        assert "🦔 Tasks" in text
        assert "Mention @PostHog" in text

    def test_each_task_renders_as_title_section_plus_context_meta(self):
        state = TasksState(
            items=(self._item(), self._item(title="Refactor mention dispatcher", status="completed", pr_url=None)),
            available_repos=("posthog/posthog",),
            has_any_tasks=True,
            page=0,
            total_pages=1,
            total_filtered=2,
        )
        view = render_home_view(**self._kwargs(tasks_state=state))
        items = self._task_items(view, expected_count=2)
        # Title is the full-size mrkdwn section; meta lives under it in a
        # context block so Slack renders it smaller/dimmer than the title.
        title, sub = items[0]
        # The title opens the Slack thread — the conversation this row summarises.
        assert title == "*<https://slack.com/archives/C1/p1234567890123456|Fix flaky retention test>*"
        assert "🔄 in progress" in sub
        assert "`posthog/posthog`" in sub
        assert "<https://app/project/1/tasks/abc|View on web>" in sub
        assert "<https://github.com/posthog/posthog/pull/123|PR>" in sub
        assert "_Updated 5m ago_" in sub

    def test_failed_task_renders_title_then_error_then_meta(self):
        state = TasksState(
            items=(
                self._item(
                    status="failed",
                    error_message="boom: timed out waiting for runner\nstack trace omitted",
                ),
            ),
            has_any_tasks=True,
            page=0,
            total_pages=1,
            total_filtered=1,
        )
        view = render_home_view(**self._kwargs(tasks_state=state))
        title, sub = self._task_items(view, expected_count=1)[0]
        assert title == "*<https://slack.com/archives/C1/p1234567890123456|Fix flaky retention test>*"
        # The supporting context block stacks the error message above the
        # standard status/repo/links/PR/updated meta. Error never replaces
        # the surrounding state.
        sub_rows = sub.split("\n\n")
        assert len(sub_rows) == 2
        # Newlines in the upstream message collapse to spaces so the row
        # doesn't blow open vertically.
        assert sub_rows[0] == "`boom: timed out waiting for runner stack trace omitted`"
        assert "❌ failed" in sub_rows[1]
        assert "`posthog/posthog`" in sub_rows[1]
        assert "<https://app/project/1/tasks/abc|View on web>" in sub_rows[1]
        assert "<https://github.com/posthog/posthog/pull/123|PR>" in sub_rows[1]
        assert "_Updated 5m ago_" in sub_rows[1]

    def test_both_task_links_render_for_a_viewer_who_can_open_them(self):
        # The desktop link dead-ends for anyone without the app, so it rides alongside the
        # web one rather than replacing it.
        state = TasksState(
            items=(self._item(desktop_url="https://us.posthog.com/code/task/abc"),),
            has_any_tasks=True,
            page=0,
            total_pages=1,
            total_filtered=1,
        )
        view = render_home_view(**self._kwargs(tasks_state=state))
        _, sub = self._task_items(view, expected_count=1)[0]

        assert "<https://app/project/1/tasks/abc|View on web>" in sub
        assert "<https://us.posthog.com/code/task/abc|View on desktop>" in sub

    def test_both_task_links_are_withheld_from_a_viewer_without_code_access(self):
        # A task page is as much a dead end for them as the desktop app, so the pair goes
        # together — the same rule the reply footer's links follow.
        state = TasksState(
            items=(self._item(posthog_url=None, desktop_url=None),),
            has_any_tasks=True,
            page=0,
            total_pages=1,
            total_filtered=1,
        )
        view = render_home_view(**self._kwargs(tasks_state=state))
        _, sub = self._task_items(view, expected_count=1)[0]

        assert "View on web" not in sub
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
        # No backticks → no repo segment; no PR link.
        assert "`" not in sub
        assert "|PR>" not in sub

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
        assert model_block["element"]["initial_option"]["value"] == "claude-opus-4-7"
        assert effort_block["element"]["initial_option"]["value"] == "high"

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
        # A row's title is a bold link — to its Slack thread, so the target is not a
        # task URL — followed by the meta line in a context block.
        titles = []
        for block in view["blocks"]:
            text = (block.get("text") or {}).get("text", "")
            if text.startswith("*<") and text.endswith(">*"):
                titles.append(text.split("|", 1)[1].rstrip(">*"))
        return titles

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
        monkeypatch.setattr(slack_app_home, "is_slack_app_home_enabled", lambda integration: True)
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
        assert "Link your PostHog account first" in text


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

    def test_model_from_another_runtime_keeps_modal_open_with_error(
        self, slack_integration, mock_slack_client, flag_on
    ):
        payload = _view_submission_payload(
            callback_id=EDIT_MODAL_PERSONAL_CALLBACK_ID,
            slack_user_id="U001",
            runtime_adapter="claude",
            model="gpt-5",
            effort=None,
        )
        response = handle_app_home_view_submission(payload)
        assert json.loads(response.content)["response_action"] == "errors"
        assert not SlackSettings.objects.filter(slack_user_id="U001").exists()


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
            "effective": AIPreferences(),
            "user_row": None,
            "is_admin": True,
            "has_project_access": False,
            "tasks_state": TasksState(),
            "stats_state": StatsState(tasks_started=4),
            "account_state": AccountState(enabled=True, link_url="https://app/link"),
            "project_state": ProjectState(candidates=(ProjectChoice(team_id=1, label="Org · Team"),)),
        }
        kwargs.update(overrides)
        return render_home_view(**kwargs)

    def test_explains_the_dead_end_and_links_to_the_settings_page(self):
        text = _all_text(self._view())

        assert "No project to show yet" in text
        assert "ask an admin" in text
        urls = [
            element["url"]
            for block in self._view()["blocks"]
            for element in block.get("elements", []) or []
            if "url" in element
        ]
        assert urls == ["http://localhost:8010/settings/project-integrations"]

    def test_suppresses_every_card_that_needs_a_project(self):
        # Each of these would otherwise render from the states passed above.
        text = _all_text(self._view())

        assert "🦔 Tasks" not in text
        assert "Workspace activity" not in text
        assert "Project routing" not in text
        assert not _action_ids(self._view())

    def test_normal_tab_is_untouched_when_a_project_is_reachable(self):
        assert "No project to show yet" not in _all_text(self._view(has_project_access=True))
