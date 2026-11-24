"""Scorers for every Slack app eval suite.

One module rather than one per suite: the suites grade a handful of recurring shapes —
did a classifier read a mention the way a person would, did it invent an instruction
nobody gave — and keeping those side by side is what makes the asymmetry between them
legible. Each scorer opts into a case through its own ``expected`` key and skips
(``score=None``) when that key is absent, so a suite lists only the scorers it wants.
"""

from __future__ import annotations

import re
from typing import Any

from products.posthog_ai.eval_harness.log_parser import LogParser
from products.posthog_ai.eval_harness.scorers import BINARY_CHOICE_SCORES, JUDGE_MODEL, JudgedScorer
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer
from products.slack_app.backend.logic.onboarding.work_focus import CLIPPED

DOCS_SEARCH_TOOL_NAME = "docs-search"


def _user_prompt(output: dict[str, Any] | None) -> str:
    if not output:
        return ""
    raw_log = output.get("raw_log")
    if raw_log:
        return LogParser.cached(raw_log, initial_prompt=output.get("prompt", "") or "").get_user_prompt()
    prompt = output.get("prompt")
    return prompt if isinstance(prompt, str) else ""


EXPECTED_KEY = "posthog_product_answer"


def _answer_under_test(output: dict[str, Any] | None, expected: Any, *, scorer_name: str) -> dict[str, Any] | Score:
    """Shared ``_prepare`` body: pull the capability under test and the final answer.

    Both judges grade the same two strings and opt in through the same ``expected``
    sub-dict, so they apply to a case together or skip together.
    """
    spec = expected.get(EXPECTED_KEY) if isinstance(expected, dict) else None
    if not isinstance(spec, dict) or not spec.get("capability"):
        return Score(name=scorer_name, score=None, metadata={"reason": "Case declares no capability to grade"})
    if not output:
        return Score(name=scorer_name, score=0.0, metadata={"reason": "No output"})
    last_message = output.get("last_message")
    if not isinstance(last_message, str) or not last_message.strip():
        return Score(name=scorer_name, score=0.0, metadata={"reason": "No final assistant message"})
    return {
        "output": {
            "prompt": _user_prompt(output),
            "last_message": last_message,
            "capability": spec["capability"],
        }
    }


class AnsweredAboutPostHogProduct(JudgedScorer):
    """Binary: does the answer explain PostHog's own product for the capability asked about?

    Opts in via ``expected={"posthog_product_answer": {"capability": "..."}}``.
    """

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        return _answer_under_test(output, expected, scorer_name=self._name())

    def __init__(self, **kwargs):
        super().__init__(
            name="posthog_product_answer",
            prompt_template="""
You are evaluating an answer the PostHog Slack app gave to a customer asking how to set something up.

PostHog ships its own product for the capability below, so the answer should be about that product — what to enable, install, or configure inside PostHog.

Capability the customer asked about:
<capability>
{{output.capability}}
</capability>

Customer's question:
<prompt>
{{output.prompt}}
</prompt>

Agent's final answer:
<final_answer>
{{output.last_message}}
</final_answer>

Does the answer explain how to do this with PostHog's own product? An answer that walks through PostHog setup steps, names the PostHog product or its settings, or links PostHog docs for it qualifies — even if some details are wrong. An answer that only discusses instrumenting the customer's own code, only asks clarifying questions, or is about some other tool does NOT qualify. Answer `yes` or `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )


class NoThirdPartyRecommendation(JudgedScorer):
    """Binary: does the answer avoid steering the customer to a non-PostHog product?

    This is the regression that prompted the suite — the agent recommending an
    external tool for a capability PostHog already sells. Opts in via the same
    ``expected={"posthog_product_answer": {"capability": "..."}}`` entry.
    """

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        return _answer_under_test(output, expected, scorer_name=self._name())

    def __init__(self, **kwargs):
        super().__init__(
            name="no_third_party_recommendation",
            prompt_template="""
You are checking whether an answer from the PostHog Slack app sent a customer to a competitor.

PostHog ships its own product for the capability below, so recommending someone else's product for it is a failure — the customer is already paying for ours.

Capability the customer asked about:
<capability>
{{output.capability}}
</capability>

Customer's question:
<prompt>
{{output.prompt}}
</prompt>

Agent's final answer:
<final_answer>
{{output.last_message}}
</final_answer>

Is the answer free of recommendations to use a non-PostHog product for this capability? Naming a third party PostHog integrates with as a data source or destination is fine, and so is naming one to explain a migration away from it. Suggesting the customer adopt, install, or evaluate someone else's product to get this capability is not. Answer `yes` if the answer is clean, `no` if it steers the customer elsewhere.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Model-override classifier
# ---------------------------------------------------------------------------

# Both scorers read the same expectation: one case states the answer once, and the
# false-positive scorer derives "this case asks for nothing" from it rather than
# carrying a second, separately-maintained flag that could disagree.
MODEL_OVERRIDE_KEY = "model_override_match"


def _reads(output: dict | None) -> tuple[str | None, str | None]:
    """The classifier's answer as a `(model, reasoning_effort)` pair.

    A `None` override — the classifier declining to steer the run — reads the same as an
    explicit pair of nulls, because that is what it means downstream.
    """
    override = (output or {}).get("override") or {}
    return override.get("model"), override.get("reasoning_effort")


class ModelOverrideMatch(Scorer):
    """Did the classifier read the mention the way a person would?

    Scores both fields at once: a run launched on the right model at the wrong effort is
    still not what the author asked for.
    """

    def _name(self) -> str:
        return MODEL_OVERRIDE_KEY

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        if output and output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": output["error"]})

        want = (expected or {}).get(MODEL_OVERRIDE_KEY)
        if want is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No expectation for this case"})

        got_model, got_effort = _reads(output)
        want_model, want_effort = want.get("model"), want.get("reasoning_effort")
        matched = got_model == want_model and got_effort == want_effort
        return Score(
            name=self._name(),
            score=1.0 if matched else 0.0,
            metadata={
                "expected_model": want_model,
                "actual_model": got_model,
                "expected_effort": want_effort,
                "actual_effort": got_effort,
            },
        )


class NoUnaskedOverride(Scorer):
    """The failure that actually costs the user something.

    The two error directions are not symmetric. Missing a real instruction falls back to
    the author's saved preferences — they notice and rephrase. Inventing an instruction
    out of subject matter silently moves someone's run onto a model they never chose, and
    nothing in the thread says so.

    Skips (`None`) on cases that do ask for something, so the score reads as a rate over
    the mentions that merely *mention* a model.
    """

    def _name(self) -> str:
        return "no_unasked_override"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        want = (expected or {}).get(MODEL_OVERRIDE_KEY) or {}
        if want.get("model") or want.get("reasoning_effort"):
            return Score(name=self._name(), score=None, metadata={"reason": "Case asks for an override"})

        if output and output.get("error"):
            # An erroring call yields no override, which is the safe answer here — but
            # scoring it as a pass would hide a broken classifier behind a good rate.
            return Score(name=self._name(), score=None, metadata={"reason": output["error"]})

        got_model, got_effort = _reads(output)
        invented = got_model is not None or got_effort is not None
        return Score(
            name=self._name(),
            score=0.0 if invented else 1.0,
            metadata={"actual_model": got_model, "actual_effort": got_effort},
        )


# ---------------------------------------------------------------------------
# Project-route classifier
# ---------------------------------------------------------------------------

PROJECT_ROUTE_KEY = "project_route_match"


def _routes_to(output: dict | None) -> int | None:
    """The integration the classifier moved the run to, or `None` for the default."""
    return ((output or {}).get("route") or {}).get("integration_id")


class ProjectRouteMatch(Scorer):
    """Did the classifier answer from the project a person would have picked?"""

    def _name(self) -> str:
        return PROJECT_ROUTE_KEY

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        if output and output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": output["error"]})

        want = (expected or {}).get(PROJECT_ROUTE_KEY)
        if want is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No expectation for this case"})

        got = _routes_to(output)
        wanted = want.get("integration_id")
        # Null keeps the run on the default, so naming the default and answering null
        # answer from the same data.
        matched = got == wanted or (got is None and want.get("is_default", False))
        return Score(
            name=self._name(),
            score=1.0 if matched else 0.0,
            metadata={"expected_integration_id": wanted, "actual_integration_id": got},
        )


class NoUnaskedProjectSwitch(Scorer):
    """The expensive direction, and worse here than for a model.

    A run moved onto the wrong model still answers the question. A run moved onto the
    wrong project answers a different question and reads as though it answered this one.
    Missing a real request only costs the author a rephrase.

    Skips (`None`) on cases that really do name a project, so the score reads as a rate
    over the mentions that should have stayed on the default.
    """

    def _name(self) -> str:
        return "no_unasked_project_switch"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        want = (expected or {}).get(PROJECT_ROUTE_KEY) or {}
        if want.get("integration_id"):
            return Score(name=self._name(), score=None, metadata={"reason": "Case names a project"})

        if output and output.get("error"):
            # A failed call routes nowhere, this scorer's passing answer — scoring it
            # would let a wholly broken classifier post a perfect rate.
            return Score(name=self._name(), score=None, metadata={"reason": output["error"]})

        got = _routes_to(output)
        return Score(
            name=self._name(),
            score=0.0 if got is not None else 1.0,
            metadata={"actual_integration_id": got},
        )


# ---------------------------------------------------------------------------
# Untagged follow-up routing
# ---------------------------------------------------------------------------

FOLLOWUP_KEY = "followup_routing"


class FollowupRoutingMatch(Scorer):
    """Did the classifier route the reply the way a person in the thread would?

    Opting in is by *presence* of the field, not truthiness — the chatter cases expect
    ``False``, and a truthiness check would skip every one of them.
    """

    def _name(self) -> str:
        return FOLLOWUP_KEY

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        want = (expected or {}).get(FOLLOWUP_KEY) or {}
        if "agent_directed" not in want:
            return Score(name=self._name(), score=None, metadata={"reason": "No expectation for this case"})
        if output and output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": output["error"]})

        got = (output or {}).get("agent_directed")
        return Score(
            name=self._name(),
            score=1.0 if got == want["agent_directed"] else 0.0,
            metadata={"expected": want["agent_directed"], "actual": got},
        )


class NoUnaskedWake(Scorer):
    """The expensive direction: waking the agent on a message nobody addressed to it.

    See ``classify_message_is_agent_directed`` for why the two errors cost differently.
    Skips on cases that really are instructions, so the score reads as a rate over the
    replies the agent should have stayed out of.
    """

    def _name(self) -> str:
        return "no_unasked_wake"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        want = (expected or {}).get(FOLLOWUP_KEY) or {}
        if want.get("agent_directed", True):
            return Score(name=self._name(), score=None, metadata={"reason": "Case is a real instruction"})
        if output and output.get("error"):
            # A failed call returns False, this scorer's passing answer — scoring it would
            # let a wholly broken classifier post a perfect rate.
            return Score(name=self._name(), score=None, metadata={"reason": output["error"]})

        return Score(
            name=self._name(),
            score=0.0 if (output or {}).get("agent_directed") else 1.0,
            metadata={"actual": (output or {}).get("agent_directed")},
        )


UNTAGGED_QUESTION_KEY = "untagged_question"


class UntaggedQuestionMatch(Scorer):
    """Did the classifier decide about answering the way a person in the channel would?"""

    def _name(self) -> str:
        return UNTAGGED_QUESTION_KEY

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        want = (expected or {}).get(UNTAGGED_QUESTION_KEY) or {}
        if "answerable" not in want:
            return Score(name=self._name(), score=None, metadata={"reason": "No expectation for this case"})
        if output and output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": output["error"]})

        got = (output or {}).get("answerable")
        return Score(
            name=self._name(),
            score=1.0 if got == want["answerable"] else 0.0,
            metadata={"expected": want["answerable"], "actual": got, "verdict": (output or {}).get("verdict")},
        )


class NoUnaskedAnswer(Scorer):
    """The expensive direction: answering a channel message PostHog cannot or should not answer.

    Skips on cases PostHog should answer, so the score reads as a rate over the messages it
    should have left alone.
    """

    def _name(self) -> str:
        return "no_unasked_answer"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        want = (expected or {}).get(UNTAGGED_QUESTION_KEY) or {}
        if want.get("answerable", True):
            return Score(name=self._name(), score=None, metadata={"reason": "Case is answerable"})
        if output and output.get("error"):
            # A failed call answers nothing, this scorer's passing answer, so it would hide an outage.
            return Score(name=self._name(), score=None, metadata={"reason": output["error"]})

        return Score(
            name=self._name(),
            score=0.0 if (output or {}).get("answerable") else 1.0,
            metadata={"actual": (output or {}).get("answerable"), "verdict": (output or {}).get("verdict")},
        )


NEEDS_REPO_KEY = "needs_repo"


class NeedsRepoMatch(Scorer):
    """Did the classifier decide about opening a repository the way an engineer reading the ask would?"""

    def _name(self) -> str:
        return NEEDS_REPO_KEY

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        want = (expected or {}).get(NEEDS_REPO_KEY) or {}
        if "needs_repo" not in want:
            return Score(name=self._name(), score=None, metadata={"reason": "No expectation for this case"})
        if output and output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": output["error"]})

        got = (output or {}).get("needs_repo")
        return Score(
            name=self._name(),
            score=1.0 if got == want["needs_repo"] else 0.0,
            metadata={"expected": want["needs_repo"], "actual": got, "probability": (output or {}).get("probability")},
        )


FEATURE_TIP_KEY = "feature_tip"


class FeatureTipMatch(Scorer):
    def _name(self) -> str:
        return FEATURE_TIP_KEY

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        want = (expected or {}).get(FEATURE_TIP_KEY) or {}
        if "feature" not in want:
            return Score(name=self._name(), score=None, metadata={"reason": "No expectation for this case"})
        if output and output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": output["error"]})

        got = (output or {}).get("feature")
        return Score(
            name=self._name(),
            score=1.0 if got == want["feature"] else 0.0,
            metadata={"expected": want["feature"], "actual": got, "verdict": (output or {}).get("verdict")},
        )


class NoForcedTip(Scorer):
    """The expensive direction: a pick for a message that no candidate fits, which makes the tip read as an ad.

    Skips on cases with a real match, so the score reads as a rate over the messages that fit nothing.
    """

    def _name(self) -> str:
        return "no_forced_tip"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        want = (expected or {}).get(FEATURE_TIP_KEY) or {}
        if want.get("feature") != "none":
            return Score(name=self._name(), score=None, metadata={"reason": "Case has a matching feature"})
        if output and output.get("error"):
            # A failed call picks nothing, this scorer's passing answer, so it would hide an outage.
            return Score(name=self._name(), score=None, metadata={"reason": output["error"]})

        got = (output or {}).get("feature")
        return Score(
            name=self._name(),
            score=1.0 if got == "none" else 0.0,
            metadata={"actual": got, "verdict": (output or {}).get("verdict")},
        )


MESSAGE_SENTIMENT_KEY = "message_sentiment"
_UNHAPPY = frozenset({"not_happy", "frustrated"})


def _sentiment_score(name: str, output: dict | None, expected: dict | None, applies: Any, passed: Any) -> Score:
    want = ((expected or {}).get(MESSAGE_SENTIMENT_KEY) or {}).get("sentiment")
    if want is None:
        return Score(name=name, score=None, metadata={"reason": "No expectation for this case"})
    if not applies(want):
        return Score(name=name, score=None, metadata={"reason": "Check does not apply to this case"})
    if output and output.get("error"):
        return Score(name=name, score=0.0, metadata={"reason": output["error"]})
    got = (output or {}).get("sentiment")
    return Score(
        name=name,
        score=1.0 if passed(want, got) else 0.0,
        metadata={"expected": want, "actual": got, "verdict": (output or {}).get("verdict")},
    )


class MessageSentimentMatch(Scorer):
    """The exact state, after production's confidence rule. The other three scorers grade what the state drives."""

    def _name(self) -> str:
        return MESSAGE_SENTIMENT_KEY

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        return _sentiment_score(self._name(), output, expected, lambda want: True, lambda want, got: got == want)


class SentimentDetected(Scorer):
    """Recall for one state: of the cases that expect it, the share that got it. ``message_sentiment``
    averages over every case, so a weak state hides behind the strong ones there."""

    def __init__(self, sentiment: str):
        self.sentiment = sentiment

    def _name(self) -> str:
        return f"{self.sentiment}_detected"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        return _sentiment_score(
            self._name(),
            output,
            expected,
            lambda want: want == self.sentiment,
            lambda want, got: got == self.sentiment,
        )


class UnhappyDetected(Scorer):
    """An unhappy person gets the reaction and the interview checks. ``not_happy`` read as ``frustrated``, or the
    other way, still passes here, because both get the same reaction."""

    def _name(self) -> str:
        return "unhappy_detected"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        return _sentiment_score(
            self._name(), output, expected, lambda want: want in _UNHAPPY, lambda want, got: got in _UNHAPPY
        )


class NoUnaskedReaction(Scorer):
    """The expensive direction: a reaction and an interview invitation to a calm person read as spam.

    Skips on unhappy cases, so the score reads as a rate over the calm messages. A failed call reacts to
    nobody, which is this scorer's passing answer, so an error scores 0 here to keep an outage visible.
    """

    def _name(self) -> str:
        return "no_unasked_reaction"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        return _sentiment_score(
            self._name(), output, expected, lambda want: want not in _UNHAPPY, lambda want, got: got not in _UNHAPPY
        )


class NoUnaskedGif(Scorer):
    """A calming GIF to a person who is only mildly dissatisfied, or not unhappy at all, reads as mockery."""

    def _name(self) -> str:
        return "no_unasked_gif"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        return _sentiment_score(
            self._name(),
            output,
            expected,
            lambda want: want != "frustrated",
            lambda want, got: got is not None and got != "frustrated",
        )


WORK_FOCUS_KEEP_KEY = "work_focus_keep"


class WorkFocusKeepMatch(Scorer):
    """Did Jev keep the message or thread as open work the way the person it is for would?"""

    def _name(self) -> str:
        return WORK_FOCUS_KEEP_KEY

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        want = (expected or {}).get(WORK_FOCUS_KEEP_KEY) or {}
        if "keep" not in want:
            return Score(name=self._name(), score=None, metadata={"reason": "No expectation for this case"})
        if output and output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": output["error"]})

        got = (output or {}).get("kept")
        return Score(
            name=self._name(),
            score=1.0 if got == want["keep"] else 0.0,
            metadata={"expected": want["keep"], "actual": got},
        )


class NoHandedOffOffer(Scorer):
    """The direction this suite exists for: an offer to do work someone already gave to another agent.

    Skips every case that is not a handoff, so the score reads as a rate over the handoffs.
    """

    def _name(self) -> str:
        return "no_handed_off_offer"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        want = (expected or {}).get(WORK_FOCUS_KEEP_KEY) or {}
        if not want.get("handed_off"):
            return Score(name=self._name(), score=None, metadata={"reason": "Case is not a handoff"})
        if output and output.get("error"):
            # A failed call keeps nothing, this scorer's passing answer, so it would hide an outage.
            return Score(name=self._name(), score=None, metadata={"reason": output["error"]})

        got = (output or {}).get("kept")
        return Score(name=self._name(), score=0.0 if got else 1.0, metadata={"actual": got})


DAILY_SUMMARY_RANK_KEY = "daily_summary_rank"


class DailySummaryRankMatch(Scorer):
    """Did Jev judge a thread's root as news the way a teammate who missed the day would?"""

    def _name(self) -> str:
        return DAILY_SUMMARY_RANK_KEY

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        want = (expected or {}).get(DAILY_SUMMARY_RANK_KEY) or {}
        if "newsworthy" not in want:
            return Score(name=self._name(), score=None, metadata={"reason": "No expectation for this case"})
        if output and output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": output["error"]})

        got = (output or {}).get("newsworthy")
        return Score(
            name=self._name(),
            score=1.0 if got == want["newsworthy"] else 0.0,
            metadata={"expected": want["newsworthy"], "actual": got, "probability": (output or {}).get("probability")},
        )


DAILY_SUMMARY_WRITE_KEY = "daily_summary_write"


def _summary_spec(expected: Any) -> dict[str, Any]:
    spec = expected.get(DAILY_SUMMARY_WRITE_KEY) if isinstance(expected, dict) else None
    return spec if isinstance(spec, dict) else {}


def _summary_sources(output: dict | None) -> list[str]:
    return [str(item.get("source")) for item in (output or {}).get("items") or []]


class SummaryCovers(Scorer):
    """The share of the threads that had to be in the summary, such as the day's incident, that it covers."""

    def _name(self) -> str:
        return "summary_covers"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        must = _summary_spec(expected).get("must_cover") or []
        if not must:
            return Score(name=self._name(), score=None, metadata={"reason": "Case requires no thread"})
        if output and output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": output["error"]})

        sources = set(_summary_sources(output))
        missed = [key for key in must if key not in sources]
        return Score(name=self._name(), score=(len(must) - len(missed)) / len(must), metadata={"missed": missed})


class SummaryOmitsChatter(Scorer):
    """The summary leaves out the threads that are only chat, also the ones the person took part in."""

    def _name(self) -> str:
        return "summary_omits_chatter"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        must_omit = _summary_spec(expected).get("must_omit") or []
        if not must_omit:
            return Score(name=self._name(), score=None, metadata={"reason": "Case has no chatter to leave out"})
        if output and output.get("error"):
            # A failed call writes nothing, this scorer's passing answer, so it would hide an outage.
            return Score(name=self._name(), score=None, metadata={"reason": output["error"]})

        included = [key for key in must_omit if key in _summary_sources(output)]
        return Score(name=self._name(), score=0.0 if included else 1.0, metadata={"included": included})


class SummaryVoice(Scorer):
    """The items follow the writer's rules: "You" for what the person did, people as tokens and never by name,
    and no em dash."""

    def _name(self) -> str:
        return "summary_voice"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        spec = _summary_spec(expected)
        items = (output or {}).get("items") or []
        if output and output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": output["error"]})
        if not items:
            return Score(name=self._name(), score=None, metadata={"reason": "The summary has no items"})

        you_for = set(spec.get("you_for") or [])
        names = spec.get("names") or []
        problems = []
        for item in items:
            text = str(item.get("text") or "")
            if item.get("source") in you_for and not text.startswith("You"):
                problems.append(f"does not start with 'You': {text}")
            if named := [name for name in names if re.search(rf"\b{re.escape(name)}\b", text)]:
                problems.append(f"names {', '.join(named)}: {text}")
            if "—" in text:
                problems.append(f"has an em dash: {text}")
        return Score(name=self._name(), score=0.0 if problems else 1.0, metadata={"problems": problems})


class SummaryNotClipped(Scorer):
    """The intro and every item fit their limits, so the code never had to cut one short."""

    def _name(self) -> str:
        return "summary_not_clipped"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        if output and output.get("error"):
            # A failed call writes nothing, this scorer's passing answer, so it would hide an outage.
            return Score(name=self._name(), score=None, metadata={"reason": output["error"]})

        texts = [str((output or {}).get("intro") or "")]
        texts += [str(item.get("text") or "") for item in (output or {}).get("items") or []]
        clipped = [text for text in texts if text.endswith(CLIPPED)]
        return Score(name=self._name(), score=0.0 if clipped else 1.0, metadata={"clipped": clipped})


class SummaryIntroFits(JudgedScorer):
    """Binary: does the intro lead into the items under it, without calling other people's work the person's own?"""

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})
        if output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": output["error"]})
        items = output.get("items") or []
        if not items:
            return Score(name=self._name(), score=None, metadata={"reason": "The summary has no items"})
        return {
            "output": {
                "person": output.get("person") or "",
                "intro": output.get("intro") or "",
                "items": "\n".join(f"- {item['text']}" for item in items),
            }
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="summary_intro_fits",
            prompt_template="""
You are checking the first line of a daily digest that PostHog sent one person in Slack. People appear as Slack tokens such as <@U0ANA>. The digest is for {{output.person}}, so an item that starts with "You" is something {{output.person}} did.

First line:
<intro>
{{output.intro}}
</intro>

Digest items under it:
<items>
{{output.items}}
</items>

Does the first line introduce these items? It passes when it describes what the items cover, or is a neutral lead-in to them. It fails when it describes topics the items do not contain, or calls the items the person's own work while most of them are things other people did. Answer `yes` when it passes, otherwise `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )


class SummaryFaithful(JudgedScorer):
    """Binary: is every summary item supported by the thread it names as its source?"""

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})
        if output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": output["error"]})
        items = output.get("items") or []
        if not items:
            return Score(name=self._name(), score=None, metadata={"reason": "The summary has no items"})
        threads = {thread["key"]: thread["text"] for thread in output.get("threads") or []}
        return {
            "output": {
                "person": output.get("person") or "",
                "items": "\n".join(f"- [{item['source']}] {item['text']}" for item in items),
                "threads": "\n\n".join(f"[{key}]\n{text}" for key, text in threads.items()),
            }
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="summary_faithful",
            prompt_template="""
You are checking a daily digest that PostHog sent one person in Slack. Each digest item names the thread it summarises in brackets. People appear as Slack tokens such as <@U0ANA>.

The digest is for {{output.person}}, so an item that starts with "You" credits {{output.person}}.

Threads:
<threads>
{{output.threads}}
</threads>

Digest items:
<items>
{{output.items}}
</items>

Is every item supported by the thread it names? An item passes when its thread shows who did it and what was decided, reported, launched or asked. An item fails when it credits the wrong person, states an outcome the thread does not reach, or adds a fact the thread does not contain. Answer `yes` only when every item passes, otherwise `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )
