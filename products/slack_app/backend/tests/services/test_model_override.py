import pytest
from unittest.mock import patch

from products.slack_app.backend.services import model_override
from products.slack_app.backend.services.model_catalogue import ModelChoice, available_model_choices
from products.slack_app.backend.services.model_override import (
    apply_model_override,
    describe_preferences,
    mentions_model_choice,
)
from products.slack_app.backend.services.slack_settings import AIPreferences

# Real model ids with their real effort support: `apply_model_override` validates
# efforts against the tasks catalogue (the authority on what a model accepts), not
# against these tuples, so inventing ids here would make the fixture lie.
CATALOGUE = (
    ModelChoice("claude", "claude-sonnet-4-6", "Claude Sonnet 4.6", ("low", "medium", "high")),
    ModelChoice("claude", "claude-fable-5", "Claude Fable 5", ("low", "medium", "high", "xhigh", "max")),
    ModelChoice("claude", "moonshotai/kimi-k3", "Moonshotai Kimi K3", ()),
    ModelChoice("codex", "gpt-5.6-sol", "gpt-5.6-sol", ("low", "medium", "high", "xhigh", "max")),
)

DEFAULT = AIPreferences(runtime_adapter="claude", model="claude-sonnet-4-6", reasoning_effort="medium")


@pytest.fixture
def catalogue():
    """`apply_model_override` reads the catalogue itself, so patch the name it resolves."""
    with patch.object(model_override, "available_model_choices", return_value=CATALOGUE):
        yield


class TestApplyModelOverride:
    @pytest.mark.parametrize(
        "requested_model,requested_effort,expected",
        [
            # A model swap drops the effort saved against the previous model rather
            # than carrying a mismatched pair into the run.
            ("claude-fable-5", None, AIPreferences("claude", "claude-fable-5", None)),
            # An effort on its own applies to whatever model the run was already using.
            (None, "high", AIPreferences("claude", "claude-sonnet-4-6", "high")),
            ("claude-fable-5", "high", AIPreferences("claude", "claude-fable-5", "high")),
            # Crossing runtimes derives the adapter from the model, never from the request.
            ("gpt-5.6-sol", None, AIPreferences("codex", "gpt-5.6-sol", None)),
            ("CLAUDE-Fable-5", None, AIPreferences("claude", "claude-fable-5", None)),
            # Nothing on offer matches, so the run keeps its resolved preferences.
            ("gemini-3-pro", None, DEFAULT),
            (None, None, DEFAULT),
            # `xhigh` is real for Fable but not for Sonnet 4.6, so it is dropped.
            ("claude-sonnet-4-6", "xhigh", AIPreferences("claude", "claude-sonnet-4-6", None)),
            # A model that exposes no effort setting at all takes none.
            ("moonshotai/kimi-k3", "high", AIPreferences("claude", "moonshotai/kimi-k3", None)),
            # An effort the run's current model can't do is dropped too.
            (None, "xhigh", AIPreferences("claude", "claude-sonnet-4-6", None)),
        ],
    )
    def test_merges_onto_the_resolved_preferences(self, catalogue, requested_model, requested_effort, expected):
        assert apply_model_override(DEFAULT, requested_model, requested_effort) == expected


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


class TestDescribePreferences:
    @pytest.mark.parametrize(
        "preferences,expected",
        [
            (AIPreferences("claude", "claude-fable-5", "high"), "*Claude Fable 5* · Reasoning: *High*"),
            (AIPreferences("claude", "claude-fable-5", None), "*Claude Fable 5*"),
            (AIPreferences("claude", "claude-opus-5", "ultracode"), "*Claude Opus 5* · Reasoning: *Ultracode*"),
        ],
    )
    def test_renders_the_shared_phrasing(self, preferences, expected):
        assert describe_preferences(preferences) == expected


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
