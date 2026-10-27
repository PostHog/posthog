"""Scorers for every Slack app eval suite.

One module rather than one per suite: the suites grade a handful of recurring shapes —
did a classifier read a mention the way a person would, did it invent an instruction
nobody gave — and keeping those side by side is what makes the asymmetry between them
legible. Each scorer opts into a case through its own ``expected`` key and skips
(``score=None``) when that key is absent, so a suite lists only the scorers it wants.
"""

from __future__ import annotations

from typing import Any

from products.posthog_ai.eval_harness.log_parser import LogParser
from products.posthog_ai.eval_harness.scorers import BINARY_CHOICE_SCORES, JUDGE_MODEL, JudgedScorer
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

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


# ---------------------------------------------------------------------------
# Reply suggestions
# ---------------------------------------------------------------------------

REPLY_OFFER_KEY = "reply_offer"


class ReplyOfferMatch(Scorer):
    """Did buttons appear exactly when the answer waits for the reader?"""

    def _name(self) -> str:
        return REPLY_OFFER_KEY

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        want = (expected or {}).get(REPLY_OFFER_KEY) or {}
        if "offer" not in want:
            return Score(name=self._name(), score=None, metadata={"reason": "No expectation for this case"})
        if output and output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": output["error"]})

        suggestions = (output or {}).get("suggestions") or []
        return Score(
            name=self._name(),
            score=1.0 if bool(suggestions) == want["offer"] else 0.0,
            metadata={"expected_offer": want["offer"], "suggestions": suggestions},
        )


class NoUnaskedButtons(Scorer):
    """Buttons under an answer that asks nothing. Skips cases that wait for the reader, so the score is a rate."""

    def _name(self) -> str:
        return "no_unasked_buttons"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        want = (expected or {}).get(REPLY_OFFER_KEY) or {}
        if want.get("offer", True):
            return Score(name=self._name(), score=None, metadata={"reason": "Case waits for the reader"})
        if output and output.get("error"):
            # A failed call offers nothing, this scorer's passing answer.
            return Score(name=self._name(), score=None, metadata={"reason": output["error"]})

        suggestions = (output or {}).get("suggestions") or []
        return Score(name=self._name(), score=0.0 if suggestions else 1.0, metadata={"suggestions": suggestions})


class SuggestedRepliesFit(JudgedScorer):
    """Binary: would the reader send every offered reply as it is?

    Grades only cases that offered replies; ``reply_offer`` already scores a missing offer.
    """

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        want = (expected or {}).get(REPLY_OFFER_KEY) or {}
        if not want.get("offer"):
            return Score(name=self._name(), score=None, metadata={"reason": "Case expects no replies"})
        suggestions = (output or {}).get("suggestions") or []
        if not suggestions:
            return Score(name=self._name(), score=None, metadata={"reason": "No replies to grade"})
        return {
            "output": {
                "answer": (output or {}).get("prompt", ""),
                "person_message": (output or {}).get("person_message") or "(not known)",
                "replies": "\n".join(f'- button "{s["label"]}" sends "{s["reply"]}"' for s in suggestions),
            }
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="suggested_replies_fit",
            prompt_template="""
You are evaluating reply buttons in a Slack thread. The PostHog agent posted the answer below. A person who reads it can send one of the replies to the agent with one click.

The person's last message before the answer:
<person_message>
{{output.person_message}}
</person_message>

Agent's answer:
<answer>
{{output.answer}}
</answer>

Offered replies:
<replies>
{{output.replies}}
</replies>

Each reply has a short button label and the full text the button sends. Every reply must:
- have a label that means the same as the text it sends
- have a label that names the choice in words, not only by its number or letter, such as "Option 2"
- read like a short message a person typed, and not every label starts with the same word, such as "Use" or "Yes"
- if the answer asks more than one question, answer every question, and not offer near-copies that change one part of a combination
- be written by the person, to the agent, as their next message in the thread
- make sense on its own, without the person typing more
- ask only for actions the answer names or clearly implies
- not guess information the answer asks the person for, such as a name, a value or a repository
- be in the same language as the answer
- mean something different from every other reply
- if the answer offers to check something first and then make a change, such as a pull request, not ask for the check and the change together unless another reply asks for the check alone

One reply is fixed on purpose. When the answer offers to fix a bug or an error, the reply that accepts the fix has the label "Fix it, make no mistakes", or its translation, and its text starts with the same words. "Make no mistakes" is not an extra action. The label stands for the fix and for the step that its text adds, such as opening a pull request.

Answer `yes` if every reply follows all of these rules. Answer `no` if one reply breaks one rule.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
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
