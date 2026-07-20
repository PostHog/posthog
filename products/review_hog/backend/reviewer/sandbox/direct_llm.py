import logging
from typing import TypeVar, cast

import pydantic
from anthropic import APIError
from anthropic.types import OutputConfigParam
from pydantic import BaseModel
from temporalio.exceptions import ApplicationError

from posthog.llm.gateway_client import get_async_anthropic_gateway_client

from products.review_hog.backend.reviewer.constants import ONESHOT_MODEL, ONESHOT_REASONING_EFFORT

_ModelT = TypeVar("_ModelT", bound=BaseModel)

logger = logging.getLogger(__name__)

# Bounds the response, not the prompt (prompt size is bounded by the callers' one-shot gates).
# A ceiling, not a spend, but adaptive thinking bills against it too and dominates the output at
# xhigh (dedup's answer is ids-only, yet a 36-finding dedup blew a 16K cap with stop_reason=max_tokens).
# 64K is sonnet-5's output limit.
_MAX_OUTPUT_TOKENS = 64_000
# A large chunking prompt at xhigh effort can legitimately take several minutes end-to-end.
_TIMEOUT_SECONDS = 600.0
# HTTP statuses that are client errors yet still worth a Temporal retry.
_RETRYABLE_CLIENT_STATUSES = (408, 409, 429)


async def run_oneshot_review(
    *,
    team_id: int,
    user_id: int,
    prompt: str,
    system_prompt: str,
    model_to_validate: type[_ModelT],
    step_name: str,
) -> _ModelT:
    """Run one review step as a single LLM-gateway call and return its validated output.

    The sandbox-free counterpart of ``run_sandbox_review`` for steps whose prompt carries everything
    inline (chunking, dedup): no repo checkout, no agent loop — one Messages call through the LLM
    gateway pinned to ``ONESHOT_MODEL`` at ``ONESHOT_REASONING_EFFORT``, with the response
    schema-constrained to ``model_to_validate`` via structured outputs (so the bare-JSON failure
    class the sandbox path retried on cannot occur). Bedrock fallback is deliberately off: the
    gateway's Bedrock path forwards only allowlisted params and would strip ``output_config``,
    silently losing both the effort pin and the schema constraint.

    Raises on failure so the calling Temporal activity retries, mirroring the sandbox contract.
    Anthropic ``APIError``s are re-raised as compact ``ApplicationError``s — a raw ``APIError``
    chain is too large for Temporal's failure serialization — with 4xx (except 408/409/429) marked
    non-retryable. ``step_name`` is stamped on the captured ``$ai_generation`` event as ``ai_stage``
    so dumps and cost queries can attribute the call to its pipeline stage.
    """
    client = get_async_anthropic_gateway_client(product="review_hog", team_id=team_id)
    async with client:
        try:
            response = await client.messages.parse(
                model=ONESHOT_MODEL,
                max_tokens=_MAX_OUTPUT_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                thinking={"type": "adaptive"},
                # The SDK's effort Literal lags the API: "xhigh" is valid for claude-sonnet-5
                # (verified live) but absent from anthropic 0.80.0's OutputConfigParam type.
                output_config=cast(OutputConfigParam, {"effort": ONESHOT_REASONING_EFFORT}),
                output_format=model_to_validate,
                metadata={"user_id": f"user-{user_id}"},
                extra_headers={"x-posthog-property-ai_stage": step_name},
                timeout=_TIMEOUT_SECONDS,
            )
        except APIError as e:
            status = getattr(e, "status_code", None)
            non_retryable = status is not None and 400 <= status < 500 and status not in _RETRYABLE_CLIENT_STATUSES
            logger.exception("One-shot %s call failed (status=%s)", step_name, status)
            raise ApplicationError(
                f"One-shot {step_name} LLM call failed: {type(e).__name__} (status={status})",
                non_retryable=non_retryable,
            ) from None
        except pydantic.ValidationError as e:
            # The SDK validates the text block against `model_to_validate` while building the parsed
            # response, so truncated/invalid JSON raises HERE — it never reaches `parsed_output`.
            # Compact like the APIError path (a raw ValidationError wraps the whole oversized payload)
            # and retryable: the exception carries no stop_reason to prove determinism.
            logger.exception("One-shot %s returned output that failed schema validation", step_name)
            raise ApplicationError(
                f"One-shot {step_name} returned unparseable output ({e.error_count()} validation error(s), "
                "likely a truncated response)"
            ) from None
    parsed = response.parsed_output
    if parsed is None:
        # No schema-valid output to parse. A refusal is retryable like a sandbox flake, but a
        # max_tokens truncation is deterministic — the retry would resubmit the same oversized
        # prompt and hit the same wall, burning the budget on a failure it can never fix.
        raise ApplicationError(
            f"One-shot {step_name} returned no parseable output (stop_reason={response.stop_reason})",
            non_retryable=response.stop_reason == "max_tokens",
        )
    return parsed
