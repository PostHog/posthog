from dataclasses import dataclass

import pytest
from unittest.mock import patch

from products.slack_app.backend.services import run_preferences
from products.slack_app.backend.services.model_catalogue import (
    ModelChoice,
    available_model_choices,
    describe_run_model,
    format_model_id,
)
from products.slack_app.backend.services.run_preferences import (
    SLACK_DEFAULT_MODEL,
    LiveRunModelChange,
    resolve_live_run_override,
    resolve_run_preferences,
)
from products.slack_app.backend.services.slack_settings import AIPreferences

# Real model ids: the resolver validates efforts against the tasks catalogue (the
# authority on what a model accepts), not against these tuples, so inventing ids here
# would make the fixture lie.
CATALOGUE = (
    ModelChoice("claude", "claude-sonnet-4-6", "Claude Sonnet 4.6", ("low", "medium", "high")),
    ModelChoice("claude", "claude-fable-5", "Claude Fable 5", ("low", "medium", "high", "xhigh", "max")),
    ModelChoice("claude", "moonshotai/kimi-k3", "Moonshotai Kimi K3", ()),
    ModelChoice("codex", "gpt-5.6-sol", "gpt-5.6-sol", ("low", "medium", "high", "xhigh", "max")),
)

SAVED = AIPreferences(runtime_adapter="claude", model="claude-sonnet-4-6", reasoning_effort="medium")


@pytest.fixture
def catalogue():
    with patch.object(run_preferences, "available_model_choices", return_value=CATALOGUE):
        yield


@dataclass
class _Override:
    """Stands in for the Temporal payload the activity returns."""

    model: str | None = None
    reasoning_effort: str | None = None


def _resolve(saved: AIPreferences, override_model=None, override_effort=None):
    """Resolve with `resolve_ai_preferences` stubbed, so these stay unit tests over the
    precedence rules rather than over the settings rows."""
    with patch.object(run_preferences, "resolve_ai_preferences", return_value=saved):
        return resolve_run_preferences(
            integration=None,  # type: ignore[arg-type]
            slack_user_id="U1",
            override=_Override(model=override_model, reasoning_effort=override_effort),
        )


class TestResolveRunPreferences:
    @pytest.mark.parametrize(
        "override_model,override_effort,expected",
        [
            # A model named in the mention replaces the pair outright — the effort saved
            # against the previous model must not ride along onto a different one.
            ("claude-fable-5", None, AIPreferences("claude", "claude-fable-5", None)),
            # An effort on its own applies to whatever model the run was already using.
            (None, "high", AIPreferences("claude", "claude-sonnet-4-6", "high")),
            ("claude-fable-5", "high", AIPreferences("claude", "claude-fable-5", "high")),
            # Crossing runtimes derives the adapter from the model, never from the request.
            ("gpt-5.6-sol", None, AIPreferences("codex", "gpt-5.6-sol", None)),
            ("CLAUDE-Fable-5", None, AIPreferences("claude", "claude-fable-5", None)),
            # Nothing on offer matches, so the run keeps its saved preferences.
            ("gemini-3-pro", None, SAVED),
            (None, None, SAVED),
            # `xhigh` is real for Fable but not for Sonnet 4.6, so it is dropped.
            ("claude-sonnet-4-6", "xhigh", AIPreferences("claude", "claude-sonnet-4-6", None)),
            # A model that exposes no effort setting at all takes none.
            ("moonshotai/kimi-k3", "high", AIPreferences("claude", "moonshotai/kimi-k3", None)),
            # An effort this model can't do leaves the run alone — including the effort
            # it already had, which an impossible ask must not clear.
            (None, "xhigh", SAVED),
        ],
    )
    def test_mention_override_precedence(self, catalogue, override_model, override_effort, expected):
        assert _resolve(SAVED, override_model, override_effort) == expected

    def test_falls_back_to_the_slack_default_when_nothing_is_saved(self, catalogue):
        """An unset workspace must still get a pinned model, not whatever the agent
        server would otherwise choose."""
        assert _resolve(AIPreferences()) == AIPreferences("claude", SLACK_DEFAULT_MODEL, None)

    def test_override_applies_on_top_of_the_default(self, catalogue):
        resolved = _resolve(AIPreferences(), override_model="claude-fable-5")
        assert resolved == AIPreferences("claude", "claude-fable-5", None)

    def test_derives_the_adapter_for_a_saved_model(self, catalogue):
        """A stored `(runtime_adapter, model)` pair that disagrees resolves to the
        adapter the model actually runs on."""
        saved = AIPreferences(runtime_adapter="codex", model="claude-fable-5", reasoning_effort=None)
        assert _resolve(saved).runtime_adapter == "claude"


class TestResolveLiveRunOverride:
    """A run already in flight can only move within the runtime its sandbox started on."""

    RUNNING = {"runtime_adapter": "claude", "model": "claude-sonnet-4-6", "reasoning_effort": "medium"}

    @pytest.mark.parametrize(
        "override_model,override_effort,expected",
        [
            # The everyday ask: a different model on the same runtime.
            ("claude-fable-5", None, LiveRunModelChange(model="claude-fable-5")),
            (None, "high", LiveRunModelChange(reasoning_effort="high")),
            ("claude-fable-5", "xhigh", LiveRunModelChange(model="claude-fable-5", reasoning_effort="xhigh")),
            # The harness is the process the sandbox launched with, so a Codex model is
            # refused outright — effort included, since it was one request.
            ("gpt-5.6-sol", "high", LiveRunModelChange(refused_model="gpt-5.6-sol")),
            # Asking for what the run is already on changes nothing.
            ("claude-sonnet-4-6", "medium", LiveRunModelChange()),
            # `xhigh` is real for Fable but not for Sonnet 4.6, so it is dropped rather
            # than sent to an agent that would reject it.
            (None, "xhigh", LiveRunModelChange()),
            (None, None, LiveRunModelChange()),
        ],
    )
    def test_only_sends_what_the_run_can_take(self, catalogue, override_model, override_effort, expected):
        assert (
            resolve_live_run_override(_Override(model=override_model, reasoning_effort=override_effort), **self.RUNNING)
            == expected
        )

    def test_derives_the_runtime_from_the_model_when_the_run_never_recorded_one(self, catalogue):
        """Runs started before models were pinned carry no adapter; the model still places them."""
        change = resolve_live_run_override(
            _Override(model="gpt-5.6-sol"),
            runtime_adapter=None,
            model="claude-sonnet-4-6",
            reasoning_effort=None,
        )
        assert change == LiveRunModelChange(refused_model="gpt-5.6-sol")

    def test_refuses_to_place_a_run_it_cannot_identify(self, catalogue):
        """With neither adapter nor model there is nothing to check a request against,
        and guessing the harness would hand the agent a model it can't load."""
        change = resolve_live_run_override(
            _Override(model="claude-fable-5"), runtime_adapter=None, model=None, reasoning_effort=None
        )
        assert change == LiveRunModelChange(refused_model="claude-fable-5")

    def test_ignores_a_model_the_catalogue_does_not_offer(self, catalogue):
        assert resolve_live_run_override(_Override(model="gemini-3-pro"), **self.RUNNING).is_empty


class TestDescribeRunModel:
    @pytest.mark.parametrize(
        "model,reasoning_effort,expected",
        [
            ("claude-fable-5", "high", "*Claude Fable 5* · Reasoning: *High*"),
            ("claude-fable-5", None, "*Claude Fable 5*"),
            ("claude-opus-5", "ultracode", "*Claude Opus 5* · Reasoning: *Ultracode*"),
        ],
    )
    def test_renders_the_shared_phrasing(self, model, reasoning_effort, expected):
        assert describe_run_model(model, reasoning_effort) == expected


class TestFormatModelId:
    @pytest.mark.parametrize(
        "model_id,expected",
        [
            ("claude-opus-5", "Claude Opus 5"),
            # A dashed version survives the split as one component.
            ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
            # Vendor initialisms keep their casing and stay glued to the version, so
            # the picker reads "GPT-5.6 Sol" rather than "Gpt 5.6 Sol".
            ("gpt-5.2", "GPT-5.2"),
            ("gpt-5.6-sol", "GPT-5.6 Sol"),
            ("gpt-5.3-codex", "GPT-5.3 Codex"),
            ("gpt-5-mini", "GPT-5 Mini"),
            # A provider-prefixed id drops the prefix before naming.
            ("openai/gpt-5.5", "GPT-5.5"),
        ],
    )
    def test_names_every_family_without_a_lookup_table(self, model_id, expected):
        assert format_model_id(model_id) == expected


class TestAvailableModelChoices:
    def test_drops_providers_we_cannot_route(self):
        """The gateway serves models under providers the tasks product has no runtime
        for; offering one would produce a run the gateway rejects."""
        from products.tasks.backend.facade.model_catalogue import GatewayModel

        gateway = (
            GatewayModel(id="claude-fable-5", owned_by="anthropic", context_window=200000),
            GatewayModel(id="titan-express", owned_by="bedrock", context_window=8000),
        )
        with patch(
            "products.tasks.backend.logic.services.model_catalogue.list_gateway_models",
            return_value=gateway,
        ):
            assert [c.model for c in available_model_choices()] == ["claude-fable-5"]
