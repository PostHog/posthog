from __future__ import annotations

from parameterized import parameterized

from products.slack_app.evals.model_classifier_scorers import EXPECTATION_KEY, ModelOverrideMatch, NoUnaskedOverride

ASKS_FOR_FABLE = {EXPECTATION_KEY: {"model": "claude-fable-5", "reasoning_effort": None}}
ASKS_FOR_NOTHING = {EXPECTATION_KEY: {"model": None, "reasoning_effort": None}}


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
