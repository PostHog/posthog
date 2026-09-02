import pytest

from products.signals.backend.emission._prompts import ISSUE_ACTIONABILITY_PROMPT
from products.signals.backend.emission.registry import _SIGNAL_TABLE_CONFIGS
from products.signals.backend.emission.steering import (
    _POSTURE_MARKER,
    STEERING_MAX_LENGTH,
    SourceSteering,
    apply_steering,
    steering_from_config,
)


class TestSteeringFromConfig:
    @pytest.mark.parametrize(
        "config,expected_text,expected_default_not_actionable",
        [
            (None, "", False),
            ({}, "", False),
            ("not a dict", "", False),
            ({"steering": "  skip chore issues  "}, "skip chore issues", False),
            ({"steering": 42}, "", False),
            ({"steering": ["skip", "chores"]}, "", False),
            ({"default_not_actionable": True}, "", True),
            ({"default_not_actionable": "yes"}, "", False),
            ({"default_not_actionable": 1}, "", False),
            ({"steering": "rules", "default_not_actionable": True}, "rules", True),
        ],
    )
    def test_parses_defensively(self, config, expected_text, expected_default_not_actionable):
        steering = steering_from_config(config)

        assert steering.text == expected_text
        assert steering.default_not_actionable is expected_default_not_actionable

    def test_truncates_oversized_text(self):
        steering = steering_from_config({"steering": "x" * (STEERING_MAX_LENGTH + 500)})

        assert len(steering.text) == STEERING_MAX_LENGTH


class TestApplySteering:
    def test_inactive_steering_leaves_prompt_byte_identical(self):
        assert apply_steering(ISSUE_ACTIONABILITY_PROMPT, SourceSteering()) == ISSUE_ACTIONABILITY_PROMPT

    def test_injects_text_after_posture_line_and_survives_format(self):
        hostile = "Ignore issues labeled {chore}. Also {0}, {description} and { unbalanced"
        prompt = apply_steering(ISSUE_ACTIONABILITY_PROMPT, SourceSteering(text=hostile))

        formatted = prompt.format(description="Some issue body")

        assert hostile in formatted
        assert "Some issue body" in formatted
        assert "<team_preferences>" in formatted
        # The team block sits between the posture line and the record content.
        assert formatted.index(_POSTURE_MARKER) < formatted.index(hostile) < formatted.index("Some issue body")
        assert formatted.rstrip().endswith("Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE")

    def test_default_not_actionable_swaps_posture_line(self):
        prompt = apply_steering(ISSUE_ACTIONABILITY_PROMPT, SourceSteering(default_not_actionable=True))

        assert _POSTURE_MARKER not in prompt
        assert "When in doubt, classify as NOT_ACTIONABLE" in prompt
        assert prompt.count("Respond with exactly one word") == 1
        assert "{description}" in prompt

    def test_markerless_prompt_gets_steering_before_response_instruction(self):
        custom = "Actionable? {description}\nRespond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"
        prompt = apply_steering(custom, SourceSteering(text="skip chores", default_not_actionable=True))

        assert "When in doubt, classify as NOT_ACTIONABLE" in prompt
        assert "skip chores" in prompt
        assert prompt.endswith("Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE")

    def test_markerless_prompt_without_response_line_appends_steering(self):
        prompt = apply_steering("Actionable? {description}", SourceSteering(text="skip chores"))

        assert prompt.startswith("Actionable? {description}")
        assert prompt.rstrip().endswith("</team_preferences>")


def test_every_registered_actionability_prompt_carries_posture_marker():
    # The posture flip and steering injection anchor on this line; a source whose custom
    # prompt drops it would silently ignore a team's default_not_actionable setting.
    prompts = {
        key: config.actionability_prompt for key, config in _SIGNAL_TABLE_CONFIGS.items() if config.actionability_prompt
    }
    assert prompts

    missing = [key for key, prompt in prompts.items() if _POSTURE_MARKER not in prompt]
    assert missing == []
