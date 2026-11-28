"""Shared wiring for sandboxed LLM-judge scorers.

The harness runs every scorer through Braintrust's ``EvalAsync``, which always
dispatches via ``eval_async`` — so judges implement only the async branch, and
``AsyncOnlyScorerMixin`` turns the never-used sync branch into an explicit error
instead of a silently divergent code path.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from copy import copy
from typing import Any

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


def needs_responses_api(model: str) -> bool:
    """Whether a judge model must go through the Responses API, which Autoevals uses only for `gpt-5` models.

    A judge answers with a function tool call. `gpt-6` models refuse function tools on chat completions unless
    `reasoning_effort` is `none`, and they do not accept `none`.
    """
    return model.startswith("gpt-6")


def responses_completion(client: AsyncOpenAI) -> Callable[..., Awaitable[dict[str, Any]]]:
    """A chat completions request sent to the Responses API, answered in the chat completions shape.

    It maps the request as Autoevals does for `gpt-5` models, so both paths send the same judge request.
    """

    async def complete(**kwargs: Any) -> dict[str, Any]:
        # A traced client's tracing arguments pass through, so the call is still traced.
        request: dict[str, Any] = {
            "model": kwargs["model"],
            "input": kwargs["messages"],
            **{key: value for key, value in kwargs.items() if key.startswith("posthog_")},
        }
        if tools := kwargs.get("tools"):
            request["tools"] = [{"type": "function", **tool["function"]} for tool in tools]
            request["tool_choice"] = "required"
        if effort := kwargs.get("reasoning_effort"):
            request["reasoning"] = {"effort": effort}
        response = await client.responses.create(**request)
        tool_calls = [
            {"id": item.call_id, "type": "function", "function": {"name": item.name, "arguments": item.arguments}}
            for item in response.output
            if item.type == "function_call"
        ]
        message: dict[str, Any] = {"role": "assistant", "content": response.output_text or None}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {"choices": [{"index": 0, "message": message, "finish_reason": "stop"}]}

    return complete


class LocalLLMClassifier(AsyncOnlyScorerMixin, LLMClassifier):
    """Use the configured OpenAI provider without Autoevals' Braintrust proxy fallback."""

    async def _run_eval_async(self, output: Any, expected: Any = None, **kwargs: Any) -> BraintrustScore:
        if self.client is not None:
            return await super()._run_eval_async(output, expected, **kwargs)
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
            if needs_responses_api(scorer.model):
                # LLMClient replaces the `complete` it is given with its own router, so set it after construction.
                scorer.client.complete = responses_completion(client)
            return await LLMClassifier._run_eval_async(scorer, output, expected, **kwargs)


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
