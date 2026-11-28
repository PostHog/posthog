from __future__ import annotations

from typing import Any

from products.posthog_ai.eval_harness.scorers import GRADED_ALIGNMENT_CHOICE_SCORES, JUDGE_MODEL, JudgedScorer
from products.posthog_ai.eval_harness.scorers.contract import Score
from products.posthog_ai.evals.product_analytics.scorers import parser_for, user_prompt

WEB_ANSWER_PROMPT = """
You are judging whether an agent correctly answered a web analytics question through PostHog's MCP tools.

The expected answer was computed from the same project with the tools' own query definitions, right before the
agent ran, so its numbers are the ground truth for this run. The tolerance says how close the agent must be and
which caveats it must state.

Judge the agent's FINAL message only. Reward an answer that names the same entities (pages, channels, countries)
in the same order and lands inside the tolerance. Penalize an answer that names different entities, that quotes
numbers outside the tolerance, that omits a caveat the tolerance requires (such as which days the period covers),
or that presents a thinly sampled page or a partial day as a finding.

User prompt:
<user_prompt>
{{output.prompt}}
</user_prompt>

Expected answer:
<expected_answer>
{{expected.expected_answer}}
</expected_answer>

Tolerance:
<tolerance>
{{expected.tolerance}}
</tolerance>

Agent's final message:
<final_message>
{{output.final_message}}
</final_message>

How would you rate the agent's final answer against the expected answer? Choose one:
- perfect: Same entities and order, numbers inside the tolerance, every required caveat stated.
- near_perfect: Inside the tolerance with a harmless extra detail or a minor omission that is not a required caveat.
- slightly_off: Right entities, but a number sits just outside the tolerance or one required caveat is missing.
- somewhat_misaligned: Partly right, but a key entity or number is wrong or an important caveat is missing.
- strongly_misaligned: Different leading entity, change in the wrong direction, or numbers far outside the tolerance.
- useless: No answer, a fabricated value, or impossible to evaluate.
""".strip()


class WebAnswerCorrectness(JudgedScorer):
    """Graded LLM judge: does the final message match the oracle the case seeder computed at run time?

    The oracle lives in ``output["seed"]["oracle"]`` rather than in the case's ``expected``, because the
    seeded project's numbers are only known once the case team exists.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            name="web_answer_correctness",
            prompt_template=WEB_ANSWER_PROMPT,
            choice_scores=GRADED_ALIGNMENT_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )

    def _prepare(self, output: dict | None, expected: dict | None) -> dict[str, Any] | Score:
        seed = (output or {}).get("seed")
        oracle = seed.get("oracle") if isinstance(seed, dict) else None
        if not isinstance(oracle, dict) or not isinstance(oracle.get("answer"), str):
            return Score(name=self._name(), score=None, metadata={"reason": "no oracle in seed"})

        parser = parser_for(output)
        final = parser.get_final_agent_message() if parser is not None else None
        if not isinstance(final, str) or not final.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "no final message"})

        return {
            "output": {"prompt": user_prompt(output), "final_message": final},
            "expected": {"expected_answer": oracle["answer"], "tolerance": oracle.get("tolerance") or "none stated"},
        }
