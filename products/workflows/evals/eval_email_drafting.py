from __future__ import annotations

import os
import json
import time
import asyncio
from functools import partial

from anthropic import AsyncAnthropic

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPrivateEval
from products.tasks.backend.model_catalog import cost_for_model
from products.workflows.evals.email_cases import CASES, drafting_instructions
from products.workflows.evals.scorers import EmailProse, EmailStructure

SUITE_KIND = SuiteKind.ONE_SHOT


async def draft_emails(case: BaseEvalCase, ctx: EvalContext, *, instructions: str) -> dict:
    started = time.monotonic()
    async with AsyncAnthropic(api_key=os.environ["LLM_GATEWAY_ANTHROPIC_API_KEY"], max_retries=0) as client:
        response = await client.messages.create(
            model=ctx.agent_model,
            max_tokens=32000,
            timeout=ctx.per_case_timeout_seconds,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=instructions,
            messages=[{"role": "user", "content": case.prompt}],
        )
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Email generation exhausted its output budget; increase max_tokens before comparing prose")
    latency_ms = round((time.monotonic() - started) * 1000)
    raw = "".join(block.text for block in response.content if block.type == "text")
    usage = response.usage
    rate = cost_for_model(ctx.agent_model)
    cost_usd = (
        (usage.input_tokens * rate.input_per_mtok + usage.output_tokens * rate.output_per_mtok) / 1_000_000
        if rate
        else None
    )
    try:
        payload = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
        emails = payload.get("emails") if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        emails = None
    return {
        "emails": emails,
        "model": ctx.agent_model,
        "latency_ms": latency_ms,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "estimated_generation_cost_usd": cost_usd,
        "cost_source": "Tasks catalog, uncached input/output list rates" if rate else "unknown model rate",
        "stop_reason": response.stop_reason,
        "last_message": raw,
    }


async def eval_email_drafting(ctx: EvalContext) -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("EmailProse needs OPENAI_API_KEY for the shared OpenAI judge")
    await OneShotPrivateEval(
        experiment_name="workflow-email-drafting",
        cases=[BaseEvalCase(**case) for case in CASES],
        scorers=[EmailStructure(), EmailProse()],
        task=partial(draft_emails, instructions=await asyncio.to_thread(drafting_instructions)),
        ctx=ctx,
    )
