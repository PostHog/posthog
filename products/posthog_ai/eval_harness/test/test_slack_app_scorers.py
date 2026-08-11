from __future__ import annotations

from parameterized import parameterized

from products.slack_app.evals.scorers import (
    FOLLOWUP_KEY,
    MODEL_OVERRIDE_KEY,
    FollowupRoutingMatch,
    ModelOverrideMatch,
    NoUnaskedOverride,
    NoUnaskedWake,
)

ASKS_FOR_FABLE = {MODEL_OVERRIDE_KEY: {"model": "claude-fable-5", "reasoning_effort": None}}
ASKS_FOR_NOTHING = {MODEL_OVERRIDE_KEY: {"model": None, "reasoning_effort": None}}


def _output(model: str | None = None, effort: str | None = None) -> dict:
    return {"override": {"model": model, "reasoning_effort": effort}}


class TestModelOverrideMatch:
    @parameterized.expand(
        [
            ("both_fields_right", _output("claude-fable-5"), ASKS_FOR_FABLE, 1.0),
            # Right model, wrong effort is still not what the author asked for — scoring
            # the fields independently would report this as a half-success.
            (
                "right_model_wrong_effort",
                _output("claude-fable-5", "max"),
                ASKS_FOR_FABLE,
                0.0,
            ),
            ("wrong_model", _output("claude-opus-5"), ASKS_FOR_FABLE, 0.0),
            ("missed_the_instruction", {"override": None}, ASKS_FOR_FABLE, 0.0),
            # A declined override and an explicit pair of nulls mean the same thing
            # downstream, so they must score the same.
            ("declined_reads_as_nulls", {"override": None}, ASKS_FOR_NOTHING, 1.0),
            ("nulls_read_as_declined", _output(), ASKS_FOR_NOTHING, 1.0),
        ]
    )
    def test_scores(self, _name, output, expected, want):
        assert ModelOverrideMatch().eval(output=output, expected=expected).score == want

    def test_classifier_error_is_a_failure_not_a_skip(self):
        score = ModelOverrideMatch().eval(output={"override": None, "error": "boom"}, expected=ASKS_FOR_FABLE)
        assert score.score == 0.0


class TestNoUnaskedOverride:
    """The suite's headline metric, so its denominator has to be right.

    It reports a rate over mentions that name a model without asking for one. If it ever
    starts scoring the instruction cases too, the rate stays high for the wrong reason —
    diluted by cases that were never at risk of this failure.
    """

    @parameterized.expand(
        [
            ("invented_a_model", _output("claude-fable-5"), 0.0),
            ("invented_an_effort", _output(None, "max"), 0.0),
            ("left_it_alone", _output(), 1.0),
            ("declined", {"override": None}, 1.0),
        ]
    )
    def test_scores_subject_matter_cases(self, _name, output, want):
        assert NoUnaskedOverride().eval(output=output, expected=ASKS_FOR_NOTHING).score == want

    @parameterized.expand(
        [
            ("obeyed", _output("claude-fable-5")),
            ("missed", {"override": None}),
        ]
    )
    def test_skips_cases_that_ask_for_an_override(self, _name, output):
        assert NoUnaskedOverride().eval(output=output, expected=ASKS_FOR_FABLE).score is None

    def test_skips_on_classifier_error(self):
        """An erroring call returns no override, which looks like the safe answer — but
        counting it as one would let a wholly broken classifier post a perfect rate.
        """
        score = NoUnaskedOverride().eval(output={"override": None, "error": "boom"}, expected=ASKS_FOR_NOTHING)
        assert score.score is None


class TestNoUnaskedWake:
    """The follow-up suite's headline metric, so its denominator has to be right.

    It reports a rate over the replies the agent should have stayed out of. Scoring the
    instruction cases too would dilute it with cases that were never at risk of a wrong
    wake-up.
    """

    @parameterized.expand(
        [
            ("stayed_asleep", {"agent_directed": False}, 1.0),
            ("woke_on_chatter", {"agent_directed": True}, 0.0),
        ]
    )
    def test_scores_chatter_cases(self, _name, output, want):
        expected = {FOLLOWUP_KEY: {"agent_directed": False}}
        assert NoUnaskedWake().eval(output=output, expected=expected).score == want

    @parameterized.expand([("forwarded", {"agent_directed": True}), ("dropped", {"agent_directed": False})])
    def test_skips_instruction_cases(self, _name, output):
        expected = {FOLLOWUP_KEY: {"agent_directed": True}}
        assert NoUnaskedWake().eval(output=output, expected=expected).score is None

    def test_skips_on_classifier_error(self):
        """A failed call returns False, which is this scorer's passing answer — counting it
        as one would let a wholly broken classifier post a perfect rate.
        """
        expected = {FOLLOWUP_KEY: {"agent_directed": False}}
        score = NoUnaskedWake().eval(output={"agent_directed": None, "error": "boom"}, expected=expected)
        assert score.score is None


class TestFollowupRoutingMatch:
    """The skip/fail protocol, which is where a routing scorer goes quietly wrong.

    Skipping where it should fail inflates its own average, and the errored call is the
    case that tempts it: the classifier returns False there, which is a real answer for
    some cases and a crash for others.
    """

    @parameterized.expand(
        [
            ("forwarded_as_expected", {"agent_directed": True}, True, 1.0),
            ("dropped_a_real_reply", {"agent_directed": False}, True, 0.0),
            # Opting in by presence, not truthiness — the chatter cases all expect False,
            # and a truthiness check would skip every one of them.
            ("chatter_left_alone", {"agent_directed": False}, False, 1.0),
            ("woke_on_chatter", {"agent_directed": True}, False, 0.0),
            ("errored_call", {"agent_directed": None, "error": "boom"}, True, 0.0),
        ]
    )
    def test_scores(self, _name, output, want, expected_score):
        expected = {FOLLOWUP_KEY: {"agent_directed": want}}
        assert FollowupRoutingMatch().eval(output=output, expected=expected).score == expected_score

    def test_skips_cases_that_declare_no_expectation(self):
        score = FollowupRoutingMatch().eval(output={"agent_directed": True}, expected={FOLLOWUP_KEY: {}})
        assert score.score is None
