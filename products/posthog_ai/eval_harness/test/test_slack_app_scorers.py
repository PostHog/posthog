from __future__ import annotations

from parameterized import parameterized

from products.slack_app.evals.scorers import (
    DAILY_SUMMARY_WRITE_KEY,
    FOLLOWUP_KEY,
    MESSAGE_SENTIMENT_KEY,
    MODEL_OVERRIDE_KEY,
    WORK_FOCUS_KEEP_KEY,
    FollowupRoutingMatch,
    MessageSentimentMatch,
    ModelOverrideMatch,
    NoHandedOffOffer,
    NoUnaskedGif,
    NoUnaskedOverride,
    NoUnaskedReaction,
    NoUnaskedWake,
    SentimentDetected,
    SummaryCovers,
    SummaryFaithful,
    SummaryNotClipped,
    SummaryOmitsChatter,
    SummaryVoice,
    UnhappyDetected,
    WorkFocusKeepMatch,
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


def _sentiment(want: str) -> dict:
    return {MESSAGE_SENTIMENT_KEY: {"sentiment": want}}


class TestMessageSentimentScorers:
    """The three group scorers are rates over different case sets. A scorer that scores cases outside its
    set reports a high rate for the wrong reason."""

    @parameterized.expand(
        [
            ("exact_match", MessageSentimentMatch, "not_happy", "not_happy", 1.0),
            ("exact_miss_inside_unhappy", MessageSentimentMatch, "frustrated", "not_happy", 0.0),
            ("unhappy_either_state_passes", UnhappyDetected, "frustrated", "not_happy", 1.0),
            ("unhappy_missed", UnhappyDetected, "not_happy", "confused", 0.0),
            ("unhappy_skips_calm_cases", UnhappyDetected, "neutral", "neutral", None),
            ("reaction_to_calm_person", NoUnaskedReaction, "confused", "not_happy", 0.0),
            ("no_reaction_to_calm_person", NoUnaskedReaction, "happy", "neutral", 1.0),
            ("reaction_skips_unhappy_cases", NoUnaskedReaction, "frustrated", "neutral", None),
            ("gif_to_mildly_unhappy_person", NoUnaskedGif, "not_happy", "frustrated", 0.0),
            ("no_gif_to_mildly_unhappy_person", NoUnaskedGif, "not_happy", "not_happy", 1.0),
            ("gif_skips_frustrated_cases", NoUnaskedGif, "frustrated", "neutral", None),
        ]
    )
    def test_scores(self, _name, scorer, want, got, expected_score):
        assert scorer().eval(output={"sentiment": got}, expected=_sentiment(want)).score == expected_score

    @parameterized.expand(
        [
            ("state_found", "confused", "confused", 1.0),
            ("state_missed", "confused", "neutral", 0.0),
            ("skips_cases_expecting_another_state", "happy", "confused", None),
        ]
    )
    def test_sentiment_detected_scores_only_its_own_state(self, _name, want, got, expected_score):
        assert (
            SentimentDetected("confused").eval(output={"sentiment": got}, expected=_sentiment(want)).score
            == expected_score
        )

    @parameterized.expand([(NoUnaskedReaction,), (NoUnaskedGif,)])
    def test_a_classifier_error_is_a_failure_on_the_guard_scorers(self, scorer):
        # A failed call reacts to nobody, which looks like a pass, so an outage would hide in the guard rates.
        score = scorer().eval(output={"sentiment": None, "error": "boom"}, expected=_sentiment("neutral"))
        assert score.score == 0.0


class TestWorkFocusHandoffScorers:
    """The handoff rate must count only handoffs, and an errored call must never pass.

    A failed Jev call keeps nothing, which is the passing answer for a handoff, so a broken
    classifier would post a perfect `no_handed_off_offer` if errors counted.
    """

    @parameterized.expand(
        [
            ("left_the_handoff_alone", {"kept": False}, True, 1.0),
            ("offered_a_handoff", {"kept": True}, True, 0.0),
            ("not_a_handoff", {"kept": True}, False, None),
            ("errored_call", {"kept": None, "error": "boom"}, True, None),
        ]
    )
    def test_no_handed_off_offer(self, _name, output, handed_off, want):
        expected = {WORK_FOCUS_KEEP_KEY: {"keep": False, "handed_off": handed_off}}
        assert NoHandedOffOffer().eval(output=output, expected=expected).score == want

    @parameterized.expand(
        [
            ("kept_a_real_ask", {"kept": True}, True, 1.0),
            ("dropped_a_real_ask", {"kept": False}, True, 0.0),
            # Opting in by presence, not truthiness, because every handoff expects False.
            ("dropped_a_handoff", {"kept": False}, False, 1.0),
            ("errored_call", {"kept": None, "error": "boom"}, False, 0.0),
        ]
    )
    def test_work_focus_keep(self, _name, output, keep, want):
        expected = {WORK_FOCUS_KEEP_KEY: {"keep": keep, "handed_off": False}}
        assert WorkFocusKeepMatch().eval(output=output, expected=expected).score == want


def _summary(*items: tuple[str, str]) -> dict:
    return {"items": [{"source": source, "text": text} for source, text in items]}


def _write_spec(**spec) -> dict:
    return {DAILY_SUMMARY_WRITE_KEY: {"names": ["Dana", "Ana"], **spec}}


class TestDailySummaryScorers:
    @parameterized.expand(
        [
            ("covers_both", _summary(("incident", "x"), ("decision", "y")), 1.0),
            ("misses_one", _summary(("incident", "x"), ("lunch", "y")), 0.5),
            ("empty_summary", _summary(), 0.0),
            ("errored_call", {"items": [], "error": "boom"}, 0.0),
        ]
    )
    def test_summary_covers(self, _name, output, want):
        expected = _write_spec(must_cover=["incident", "decision"])
        assert SummaryCovers().eval(output=output, expected=expected).score == want

    @parameterized.expand(
        [
            ("left_out", _summary(("incident", "x")), 1.0),
            ("kept_the_lunch", _summary(("lunch", "<@U0RAJ> organised tacos")), 0.0),
            # A failed call writes nothing, which would pass, so it must not count.
            ("errored_call", {"items": [], "error": "boom"}, None),
        ]
    )
    def test_summary_omits_chatter(self, _name, output, want):
        expected = _write_spec(must_omit=["lunch"])
        assert SummaryOmitsChatter().eval(output=output, expected=expected).score == want

    @parameterized.expand(
        [
            ("follows_the_rules", _summary(("decision", "You cut the trial to 14 days")), 1.0),
            ("third_person_for_the_person", _summary(("decision", "<@U0DANA> cut the trial to 14 days")), 0.0),
            ("names_a_person", _summary(("incident", "Ana rolled back the deploy")), 0.0),
            # A name inside a longer word is not a name.
            ("name_inside_a_word", _summary(("incident", "<@U0BEN> fixed Analytics exports")), 1.0),
            ("em_dash", _summary(("incident", "<@U0BEN> rolled back \u2014 fixed")), 0.0),
            ("no_items", _summary(), None),
        ]
    )
    def test_summary_voice(self, _name, output, want):
        expected = _write_spec(you_for=["decision"])
        assert SummaryVoice().eval(output=output, expected=expected).score == want

    def test_summary_faithful_tells_the_judge_who_you_is(self):
        output = {
            "person": "<@U0DANA>",
            **_summary(("decision", "You cut the trial to 14 days")),
            "threads": [{"key": "decision", "text": "<@U0DANA>: Decided: 14 day trials"}],
        }
        prepared = SummaryFaithful()._prepare(output, _write_spec())
        assert isinstance(prepared, dict) and prepared["output"]["person"] == "<@U0DANA>"

    @parameterized.expand(
        [
            ("fits", {"intro": "Since yesterday: a fix", **_summary(("incident", "<@U0BEN> rolled back"))}, 1.0),
            ("clipped_intro", {"intro": "Since yesterday: a…", **_summary(("incident", "x"))}, 0.0),
            ("clipped_item", {"intro": "Since yesterday", **_summary(("incident", "<@U0BEN> rolled…"))}, 0.0),
            # A failed call writes nothing, which would pass, so it must not count.
            ("errored_call", {"items": [], "error": "boom"}, None),
        ]
    )
    def test_summary_not_clipped(self, _name, output, want):
        assert SummaryNotClipped().eval(output=output, expected=_write_spec()).score == want
