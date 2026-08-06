"""Scorers for the Slack app's answers to "how do I set up X?" questions."""

from __future__ import annotations

from typing import Any

from products.posthog_ai.eval_harness.log_parser import LogParser
from products.posthog_ai.eval_harness.scorers import BINARY_CHOICE_SCORES, JUDGE_MODEL, JudgedScorer
from products.posthog_ai.eval_harness.scorers.contract import Score

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
