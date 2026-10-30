"""Shared wiring for sandboxed LLM-judge scorers.

The harness runs every scorer through Braintrust's ``EvalAsync``, which always
dispatches via ``eval_async`` — so judges implement only the async branch, and
``AsyncOnlyScorerMixin`` turns the never-used sync branch into an explicit error
instead of a silently divergent code path.
"""

from __future__ import annotations

import os
from copy import copy
from typing import Any

from anthropic import AsyncAnthropic
from autoevals.llm import LLMClassifier
from autoevals.oai import LLMClient
from braintrust import Score as BraintrustScore
from openai import AsyncOpenAI, RateLimitError

from ..engines.types import ScorerResult
from .contract import AsyncOnlyScorerMixin, Score

# Re-exported for back-compat: AsyncOnlyScorerMixin now lives in the scorer contract.
__all__ = [
    "BINARY_CHOICE_SCORES",
    "GRADED_ALIGNMENT_CHOICE_SCORES",
    "JUDGE_MODEL",
    "AsyncOnlyScorerMixin",
    "JudgedScorer",
    "judge_model",
]

BINARY_CHOICE_SCORES = {"yes": 1.0, "no": 0.0}

GRADED_ALIGNMENT_CHOICE_SCORES = {
    "perfect": 1.0,
    "near_perfect": 0.9,
    "slightly_off": 0.75,
    "somewhat_misaligned": 0.5,
    "strongly_misaligned": 0.25,
    "useless": 0.0,
}

JUDGE_MODEL = "gpt-5.4"

JUDGE_MODEL_ENV = "EVAL_JUDGE_MODEL"
DEFAULT_CONFIGURABLE_JUDGE_MODEL = "claude-opus-5-5"
_ANTHROPIC_JUDGE_MAX_TOKENS = 16_000
_ANTHROPIC_JUDGE_SYSTEM = (
    "Reply with the JSON object that the response format describes. It replaces the select_choice call."
)


def judge_model() -> str:
    """Judge model for suites that opt into a configurable judge.

    ``JUDGE_MODEL`` stays pinned for the suites that use it, so changing ``EVAL_JUDGE_MODEL``
    never moves an existing suite's scores.
    """
    return os.environ.get(JUDGE_MODEL_ENV) or DEFAULT_CONFIGURABLE_JUDGE_MODEL


def is_anthropic_model(model: str) -> bool:
    return model.startswith("claude-")


def _anthropic_api_key() -> str | None:
    # The harness preflight already requires the gateway's Anthropic key, so a judge needs no new secret.
    return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("LLM_GATEWAY_ANTHROPIC_API_KEY")


class LocalLLMClassifier(AsyncOnlyScorerMixin, LLMClassifier):
    """Use the configured provider directly, without Autoevals' Braintrust proxy fallback.

    Models named ``claude-*`` go to the Anthropic API, everything else to the OpenAI API.
    """

    async def _run_eval_async(self, output: Any, expected: Any = None, **kwargs: Any) -> BraintrustScore:
        if self.client is not None:
            return await super()._run_eval_async(output, expected, **kwargs)
        if is_anthropic_model(self.model):
            return await self._run_anthropic_eval(output, expected, **kwargs)
        async with AsyncOpenAI() as client:
            scorer = copy(self)
            scorer.client = LLMClient(
                openai=client,
                complete=client.chat.completions.create,
                embed=client.embeddings.create,
                moderation=client.moderations.create,
                is_async=True,
                RateLimitError=RateLimitError,
            )
            return await LLMClassifier._run_eval_async(scorer, output, expected, **kwargs)

    async def _run_anthropic_eval(self, output: Any, expected: Any, **kwargs: Any) -> BraintrustScore:
        # Current Claude models reject a forced tool choice, so the choice comes back as structured
        # output with the same schema Autoevals gives its select_choice tool.
        request = await self._request_args_async(output, expected, **kwargs)
        schema = {**self.classification_tools[0]["function"]["parameters"], "additionalProperties": False}
        async with AsyncAnthropic(api_key=_anthropic_api_key()) as client:
            response = await client.messages.create(
                model=self.model,
                max_tokens=_ANTHROPIC_JUDGE_MAX_TOKENS,
                system=_ANTHROPIC_JUDGE_SYSTEM,
                messages=request["messages"],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        if response.stop_reason == "refusal":
            raise ValueError("Anthropic judge refused the request")
        arguments = "".join(block.text for block in response.content if block.type == "text")
        return self._process_response({"tool_calls": [{"function": {"name": "select_choice", "arguments": arguments}}]})


class JudgedScorer(LocalLLMClassifier):
    """Base class for sandboxed LLM judges.

    Subclasses implement ``_prepare(output, expected)`` returning either a
    ``Score`` to short-circuit (no LLM call), or a dict with ``output`` — and
    optionally ``expected`` — to forward to the LLM judge as template variables.

    Both the short-circuit paths and judge-call exceptions map to
    ``score=0.0`` rather than ``score=None`` — Braintrust treats ``None`` as
    "skipped" and drops it from the aggregate, which silently hides broken
    judges and missing query inputs. We want those to surface as failing
    scores instead. Judges that should genuinely self-skip (e.g. the graded
    tool never ran and another scorer covers that) return ``Score(score=None)``
    from ``_prepare`` deliberately.
    """

    async def _run_eval_async(self, output: Any, expected: Any = None, **kwargs: Any) -> BraintrustScore:
        prepared = self._prepare(output, expected)
        if isinstance(prepared, BraintrustScore):
            return prepared
        try:
            return await super()._run_eval_async(prepared["output"], prepared.get("expected"), **kwargs)
        except Exception as exc:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": f"judge error: {exc}"},
                result=ScorerResult(status="error", error_code="judge_error", error_message=str(exc)),
            )

    def _prepare(self, output: Any, expected: Any) -> dict[str, Any] | BraintrustScore:
        raise NotImplementedError
