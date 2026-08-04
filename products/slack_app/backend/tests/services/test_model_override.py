import pytest
from unittest.mock import patch

from products.slack_app.backend.services import model_override
from products.slack_app.backend.services.model_override import (
    ModelChoice,
    apply_model_override,
    available_model_choices,
    describe_preferences,
    mentions_model_choice,
)
from products.slack_app.backend.services.slack_app_home import PickerAdapter, PickerEffort, PickerModel
from products.slack_app.backend.services.slack_settings import AIPreferences

CATALOGUE = (
    ModelChoice("claude", "claude-opus-5", "Claude Opus 5", ("low", "medium", "high", "max")),
    ModelChoice("claude", "claude-fable-5", "Claude Fable 5", ("low", "medium", "high")),
    ModelChoice("claude", "moonshotai/kimi-k3", "Moonshotai Kimi K3", ()),
    ModelChoice("codex", "gpt-5.6-sol", "gpt-5.6-sol", ("low", "medium", "high", "max")),
)

DEFAULT = AIPreferences(runtime_adapter="claude", model="claude-opus-5", reasoning_effort="medium")


@pytest.fixture(autouse=True)
def catalogue():
    with patch.object(model_override, "available_model_choices", return_value=CATALOGUE):
        yield


class TestModelOverride:
    @pytest.mark.parametrize(
        "requested_model,requested_effort,expected",
        [
            # A model swap drops the effort saved against the previous model rather
            # than carrying a mismatched pair into the run.
            ("claude-fable-5", None, AIPreferences("claude", "claude-fable-5", None)),
            # An effort on its own applies to whatever model the run was already using.
            (None, "high", AIPreferences("claude", "claude-opus-5", "high")),
            ("claude-fable-5", "high", AIPreferences("claude", "claude-fable-5", "high")),
            # Crossing runtimes derives the adapter from the model, never from the request.
            ("gpt-5.6-sol", None, AIPreferences("codex", "gpt-5.6-sol", None)),
            ("CLAUDE-Fable-5", None, AIPreferences("claude", "claude-fable-5", None)),
            # Nothing on offer matches, so the run keeps its resolved preferences.
            ("gemini-3-pro", None, DEFAULT),
            (None, None, DEFAULT),
            # `max` is real for Opus but not for Fable, so it is dropped on the swap.
            ("claude-fable-5", "max", AIPreferences("claude", "claude-fable-5", None)),
            # A model that exposes no effort setting at all takes none.
            ("moonshotai/kimi-k3", "high", AIPreferences("claude", "moonshotai/kimi-k3", None)),
            # An effort the current model can't do leaves the run untouched.
            (None, "xhigh", AIPreferences("claude", "claude-opus-5", None)),
        ],
    )
    def test_apply_model_override(self, requested_model, requested_effort, expected):
        assert apply_model_override(DEFAULT, requested_model, requested_effort) == expected

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
    def test_mentions_model_choice(self, text, expected):
        assert mentions_model_choice(text) is expected

    @pytest.mark.parametrize(
        "preferences,expected",
        [
            (AIPreferences("claude", "claude-fable-5", "high"), "*Claude Fable 5* · Reasoning: *High*"),
            (AIPreferences("claude", "claude-fable-5", None), "*Claude Fable 5*"),
            # `ultracode` is a newer effort; an unmapped value must still render.
            (AIPreferences("claude", "claude-opus-5", "ultracode"), "*Claude Opus 5* · Reasoning: *Ultracode*"),
        ],
    )
    def test_describe_preferences(self, preferences, expected):
        assert describe_preferences(preferences) == expected


class TestAvailableModelChoices:
    def test_flattens_the_picker_tree(self):
        picker = (
            PickerAdapter(
                value="claude",
                label="Claude (Anthropic)",
                models=(
                    PickerModel(
                        value="claude-fable-5",
                        label="Claude Fable 5",
                        supported_efforts=(PickerEffort(value="high", label="High"),),
                    ),
                ),
            ),
        )
        with patch(
            "products.slack_app.backend.services.slack_app_home.get_picker_choices",
            return_value=picker,
        ):
            assert available_model_choices() == (ModelChoice("claude", "claude-fable-5", "Claude Fable 5", ("high",)),)
