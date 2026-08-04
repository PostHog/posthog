import pytest
from unittest.mock import patch

from products.slack_app.backend.services import run_preferences
from products.slack_app.backend.services.model_catalogue import ModelChoice, available_model_choices
from products.slack_app.backend.services.run_preferences import (
    SLACK_DEFAULT_MODEL,
    describe_run_model,
    mentions_model_choice,
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


def _resolve(saved: AIPreferences, override_model=None, override_effort=None):
    """Resolve with `resolve_ai_preferences` stubbed, so these stay unit tests over the
    precedence rules rather than over the settings rows."""
    with patch.object(run_preferences, "resolve_ai_preferences", return_value=saved):
        return resolve_run_preferences(
            integration=None,  # type: ignore[arg-type]
            slack_user_id="U1",
            override_model=override_model,
            override_effort=override_effort,
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


class TestMentionsModelChoice:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("use fable for this one", True),
            ("run it on claude-fable-5 please", True),
            ("do this with max effort", True),
            ("give it more thinking", True),
            ("fix the flaky checkout test", False),
            # Bare effort words are deliberately not triggers — they are ordinary
            # Slack English and would send every mention to the classifier.
            ("this is high priority, please look now", False),
            # Model ids contribute their word parts, so the match has to respect word
            # boundaries: `sol` from gpt-5.6-sol must not fire on `solution`.
            ("ship the solution we discussed", False),
        ],
    )
    def test_pre_filter(self, text, expected):
        assert mentions_model_choice(text, CATALOGUE) is expected


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


class TestAvailableModelChoices:
    def test_drops_providers_we_cannot_route(self):
        """The gateway serves models under providers the tasks product has no runtime
        for; offering one would produce a run the gateway rejects."""
        from products.slack_app.backend.services.llm_models import GatewayModel

        gateway = (
            GatewayModel(id="claude-fable-5", owned_by="anthropic", context_window=200000),
            GatewayModel(id="titan-express", owned_by="bedrock", context_window=8000),
        )
        with patch(
            "products.slack_app.backend.services.llm_models.list_slack_app_models",
            return_value=gateway,
        ):
            assert [c.model for c in available_model_choices()] == ["claude-fable-5"]
