from typing import Any

import pytest
from unittest.mock import patch

from django.core.exceptions import ValidationError

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.feature_flags import SLACK_APP_HOME_FLAG
from products.slack_app.backend.models import SlackSettings, UntaggedFollowupMode
from products.slack_app.backend.services.slack_settings import (
    AIPreferences,
    resolve_ai_preferences,
    resolve_untagged_followup_mode,
    validate_ai_preferences,
)


@pytest.fixture
def slack_setup(db):
    organization = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=organization, name="Team")
    integration = Integration.objects.create(
        team=team,
        kind="slack",
        integration_id="T_WS",
        sensitive_config={"access_token": "xoxb"},
    )
    return integration


@pytest.fixture
def flag_on():
    """Flip the slack-app-home flag on for the duration of a test."""
    with patch(
        "products.slack_app.backend.feature_flags.posthoganalytics.feature_enabled",
        return_value=True,
    ) as mock:
        yield mock


@pytest.fixture
def flag_off():
    with patch(
        "products.slack_app.backend.feature_flags.posthoganalytics.feature_enabled",
        return_value=False,
    ) as mock:
        yield mock


@pytest.fixture(autouse=True)
def _stub_task_runtime_helpers():
    """Replace the lazy tasks-facade imports with a minimal stub.

    Slack handler code imports `products.tasks.backend.facade.run_config`,
    which re-exports from `products.tasks.backend.temporal.process_task.utils`.
    Loading either pulls in `tasks.backend.temporal.__init__.py`, which
    eagerly loads the docker sandbox class. The test env sets
    `SANDBOX_PROVIDER=docker` alongside `DEBUG=False` — a combination the
    sandbox module rejects at import time. Production runs
    `SANDBOX_PROVIDER=modal`, so the real lazy import path works there.
    Stubbing the facade module here keeps these tests focused on resolver
    logic without dragging the tasks-temporal import chain in.
    """
    supported_by_model = {
        ("claude", "claude-opus-4-7"): {"low", "medium", "high", "xhigh", "max"},
        ("claude", "claude-sonnet-4-6"): {"low", "medium", "high"},
        ("codex", "gpt-5.5"): {"low", "medium", "high", "xhigh"},
        ("codex", "gpt-5"): {"low", "medium", "high"},
    }

    class _Effort:
        def __init__(self, value: str):
            self.value = value

    def fake_get_supported(adapter, model):
        return tuple(_Effort(v) for v in supported_by_model.get((adapter, model), set()))

    def fake_get_error(adapter, model, effort):
        if adapter is None or model is None or effort is None:
            return None
        supported = supported_by_model.get((adapter, model), set())
        if effort in supported:
            return None
        return f"Reasoning effort '{effort}' is not supported for {adapter}/{model}."

    models_by_adapter = {
        "claude": ("claude-opus-4-7", "claude-sonnet-4-6"),
        "codex": ("gpt-5", "gpt-5.5"),
    }

    def fake_validate_selection(adapter, model, effort):
        if adapter is not None and adapter not in models_by_adapter:
            raise ValidationError(f"Unknown runtime_adapter '{adapter}'.")
        owning = next((a for a, models in models_by_adapter.items() if model in models), None)
        if adapter is not None and owning is not None and owning != adapter:
            raise ValidationError(f"Model '{model}' runs on runtime_adapter '{owning}', not '{adapter}'.")
        error = fake_get_error(adapter, model, effort)
        if error:
            raise ValidationError(error)

    class _Adapter:
        def __init__(self, value):
            self.value = value

    class _RuntimeAdapter:
        CLAUDE = _Adapter("claude")
        CODEX = _Adapter("codex")

        def __iter__(self):
            return iter([self.CLAUDE, self.CODEX])

    class _PublicEffort:
        def __init__(self, value):
            self.value = value

    public_efforts = (
        _PublicEffort("low"),
        _PublicEffort("medium"),
        _PublicEffort("high"),
        _PublicEffort("xhigh"),
        _PublicEffort("max"),
    )

    import sys
    from types import ModuleType

    module_name = "products.tasks.backend.facade.run_config"
    # `Any` annotation so mypy accepts the stub-attribute assignments below —
    # the stdlib `ModuleType` rejects them, and ruff B010 reverts any
    # `setattr` workaround back to attribute syntax.
    fake: Any = ModuleType(module_name)
    fake.get_supported_reasoning_efforts = fake_get_supported
    fake.get_reasoning_effort_error = fake_get_error
    fake.get_models_for_runtime_adapter = lambda adapter: models_by_adapter.get(adapter, ())
    fake.validate_model_selection = fake_validate_selection
    fake.RuntimeAdapter = _RuntimeAdapter()
    fake.PUBLIC_REASONING_EFFORTS = public_efforts

    saved = sys.modules.get(module_name)
    sys.modules[module_name] = fake
    try:
        yield
    finally:
        if saved is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = saved


class TestResolveAIPreferences:
    @pytest.mark.parametrize(
        "user_row,workspace_row,expected",
        [
            pytest.param(
                None,
                None,
                AIPreferences(),
                id="no-rows-returns-empty",
            ),
            pytest.param(
                None,
                {"runtime_adapter": "claude", "model": "claude-opus-4-7", "effort": "high"},
                AIPreferences(),
                id="workspace-row-is-ignored",
            ),
            pytest.param(
                {"runtime_adapter": "codex", "model": "gpt-5.5", "effort": "high"},
                None,
                AIPreferences(runtime_adapter="codex", model="gpt-5.5", reasoning_effort="high"),
                id="user-only-applies",
            ),
            pytest.param(
                {"runtime_adapter": "claude", "model": "claude-opus-4-7", "effort": "high"},
                {"runtime_adapter": "codex", "model": "gpt-5.5", "effort": "low"},
                AIPreferences(runtime_adapter="claude", model="claude-opus-4-7", reasoning_effort="high"),
                id="user-wins-over-lingering-workspace-row",
            ),
        ],
    )
    def test_resolution_table(self, slack_setup, flag_on, user_row, workspace_row, expected):
        integration = slack_setup
        if user_row:
            SlackSettings.objects.create(
                default_integration=integration,
                slack_workspace_id="T_WS",
                slack_user_id="U001",
                ai_preferences={
                    "runtime_adapter": user_row["runtime_adapter"],
                    "model": user_row["model"],
                    "reasoning_effort": user_row["effort"],
                },
            )
        if workspace_row:
            SlackSettings.objects.create(
                default_integration=integration,
                slack_workspace_id="T_WS",
                slack_user_id=None,
                ai_preferences={
                    "runtime_adapter": workspace_row["runtime_adapter"],
                    "model": workspace_row["model"],
                    "reasoning_effort": workspace_row["effort"],
                },
            )
        assert resolve_ai_preferences(integration, "U001") == expected

    def test_user_row_with_no_pair_reads_as_no_preference(self, slack_setup, flag_on):
        """A user row without the atomic `(runtime_adapter, model)` pair is
        treated as "no personal preference" — the orphaned effort never leaks
        into the resolved triple."""
        integration = slack_setup
        SlackSettings.objects.create(
            default_integration=integration,
            slack_workspace_id="T_WS",
            slack_user_id="U001",
            # Orphan effort with no pair — shouldn't reach the DB through the
            # normal write path, but the resolver still has to defend against
            # it (direct writes, older data, schema drift).
            ai_preferences={"reasoning_effort": "medium"},
        )

        assert resolve_ai_preferences(integration, "U001") == AIPreferences()

    def test_unsupported_effort_dropped_when_model_does_not_support_it(self, slack_setup, flag_on):
        """If a row stores an effort the resolved model can't honour (e.g.
        the model definition changed since the effort was saved), the
        resolver drops it rather than letting it leak through to the task
        layer."""
        integration = slack_setup
        SlackSettings.objects.create(
            default_integration=integration,
            slack_workspace_id="T_WS",
            slack_user_id="U001",
            # `xhigh` isn't in `supported_by_model` for sonnet-4-6, so the
            # runtime drop must clear it.
            ai_preferences={
                "runtime_adapter": "claude",
                "model": "claude-sonnet-4-6",
                "reasoning_effort": "xhigh",
            },
        )
        result = resolve_ai_preferences(integration, "U001")
        assert result.runtime_adapter == "claude"
        assert result.model == "claude-sonnet-4-6"
        assert result.reasoning_effort is None

    def test_user_id_none_resolves_empty(self, slack_setup, flag_on):
        # No Slack user to attribute the run to, so there's no preference to
        # apply — the workspace row's AI fields are no longer consulted.
        integration = slack_setup
        SlackSettings.objects.create(
            default_integration=integration,
            slack_workspace_id="T_WS",
            slack_user_id=None,
            ai_preferences={"runtime_adapter": "claude", "model": "claude-opus-4-7", "reasoning_effort": "high"},
        )
        assert resolve_ai_preferences(integration, None) == AIPreferences()

    def test_flag_off_returns_empty_even_with_rows_present(self, slack_setup, flag_off):
        integration = slack_setup
        SlackSettings.objects.create(
            default_integration=integration,
            slack_workspace_id="T_WS",
            slack_user_id="U001",
            ai_preferences={"runtime_adapter": "claude", "model": "claude-opus-4-7", "reasoning_effort": "high"},
        )
        assert resolve_ai_preferences(integration, "U001") == AIPreferences()

    def test_flag_check_failure_fails_closed(self, slack_setup):
        integration = slack_setup
        SlackSettings.objects.create(
            default_integration=integration,
            slack_workspace_id="T_WS",
            slack_user_id="U001",
            ai_preferences={"runtime_adapter": "claude", "model": "claude-opus-4-7", "reasoning_effort": "high"},
        )
        with patch(
            "products.slack_app.backend.feature_flags.posthoganalytics.feature_enabled",
            side_effect=RuntimeError("boom"),
        ):
            assert resolve_ai_preferences(integration, "U001") == AIPreferences()


class TestResolveUntaggedFollowupMode:
    @pytest.mark.parametrize(
        "stored,expected",
        [
            (UntaggedFollowupMode.ASK, UntaggedFollowupMode.ASK),
            (UntaggedFollowupMode.NEVER, UntaggedFollowupMode.NEVER),
            (UntaggedFollowupMode.AUTO, UntaggedFollowupMode.AUTO),
            # A row that predates the column, and a value retired since it was written,
            # both leave the feature off rather than opting someone in by accident.
            (None, UntaggedFollowupMode.NEVER),
            ("retired-value", UntaggedFollowupMode.NEVER),
        ],
    )
    def test_stored_value_governs_with_never_as_the_floor(self, slack_setup, stored, expected):
        integration = slack_setup
        SlackSettings.objects.create(
            slack_workspace_id="T_WS",
            slack_user_id="U001",
            untagged_followup_mode=stored,
        )
        assert resolve_untagged_followup_mode(integration, "U001") == expected

    def test_no_row_at_all_resolves_never(self, slack_setup):
        assert resolve_untagged_followup_mode(slack_setup, "U001") == UntaggedFollowupMode.NEVER

    def test_another_users_choice_does_not_leak(self, slack_setup):
        # The mode is read per thread creator, so one person opting in must not
        # turn follow-ups on in everybody else's threads.
        integration = slack_setup
        SlackSettings.objects.create(
            slack_workspace_id="T_WS",
            slack_user_id="U002",
            untagged_followup_mode=UntaggedFollowupMode.AUTO,
        )
        assert resolve_untagged_followup_mode(integration, "U001") == UntaggedFollowupMode.NEVER


class TestValidateAIPreferences:
    def test_all_none_is_valid(self):
        validate_ai_preferences(None, None, None)

    def test_full_triple_is_valid(self):
        validate_ai_preferences("claude", "claude-opus-4-7", "high")

    def test_pair_without_effort_is_valid(self):
        validate_ai_preferences("claude", "claude-opus-4-7", None)

    @pytest.mark.parametrize(
        "runtime_adapter,model",
        [
            ("claude", None),
            (None, "claude-opus-4-7"),
        ],
    )
    def test_half_set_pair_rejected(self, runtime_adapter, model):
        with pytest.raises(ValidationError, match="must be set together"):
            validate_ai_preferences(runtime_adapter, model, None)

    def test_unknown_runtime_adapter_rejected(self):
        with pytest.raises(ValidationError, match="Unknown runtime_adapter"):
            validate_ai_preferences("nonsense", "claude-opus-4-7", None)

    def test_model_from_another_runtime_rejected(self):
        # The modal offers both runtimes' models, so nothing but this check stops a
        # Claude + GPT pair from being written and handed to a run.
        with pytest.raises(ValidationError, match="runs on runtime_adapter"):
            validate_ai_preferences("claude", "gpt-5.5", None)

    def test_unknown_reasoning_effort_rejected(self):
        with pytest.raises(ValidationError, match="Unknown reasoning_effort"):
            validate_ai_preferences("claude", "claude-opus-4-7", "ultra")

    def test_effort_unsupported_by_model_rejected(self):
        with pytest.raises(ValidationError, match="not supported"):
            validate_ai_preferences("claude", "claude-sonnet-4-6", "xhigh")

    def test_flag_constant_is_stable(self):
        # Sanity: the flag name is what we documented and rolled out with.
        assert SLACK_APP_HOME_FLAG == "slack-app-home"
