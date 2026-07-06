"""LLM-as-judge wiring.

Builds a :class:`JudgeFn` on top of the signals ``call_llm`` helper, so judge calls reuse
the same gateway client, retry-on-validation, and per-team cost attribution as the rest of
the pipeline. Judges are only constructed in judge/live mode; deterministic replay never
needs the gateway.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from products.signals.eval.agentic.scoring import JudgeFn, JudgeVerdict


class _JudgeResult(BaseModel):
    score: float = Field(ge=0.0, le=1.0, description="Quality score from 0 (fails the rubric) to 1 (fully meets it).")
    passed: bool = Field(description="Whether the output meets the rubric's bar.")
    reasoning: str = Field(description="One or two sentences justifying the score, citing specifics.")


_JUDGE_SYSTEM = (
    "You are a meticulous evaluation judge for an automated engineering agent. "
    "Grade the agent's output strictly against the rubric. Reward specific, evidence-grounded "
    "work; penalize vagueness, unsupported claims, and rubric misses. Respond only with JSON "
    "matching the schema."
)


def build_call_llm_judge(*, team_id: int | None) -> JudgeFn:
    """A judge backed by the signals gateway ``call_llm`` helper."""
    from products.signals.backend.temporal.llm import call_llm  # noqa: PLC0415 — keeps gateway import lazy

    async def _judge(*, system: str, prompt: str, rubric: str | None = None) -> JudgeVerdict:
        schema = _JudgeResult.model_json_schema()
        user_prompt = (
            f"{prompt}\n\n"
            f"## Rubric\n{rubric or 'Grade overall quality and faithfulness.'}\n\n"
            f"Respond with JSON matching this schema:\n{schema}"
        )
        result = await call_llm(
            team_id=team_id,
            system_prompt=f"{_JUDGE_SYSTEM}\n\n{system}",
            user_prompt=user_prompt,
            validate=_JudgeResult.model_validate_json,
            stage="eval_judge",
        )
        return JudgeVerdict(passed=result.passed, score=result.score, reasoning=result.reasoning)

    return _judge
