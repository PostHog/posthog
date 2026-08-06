"""Can the bot diagnose a real CI failure?

One model call per case against a failure that actually happened, scored on the four axes in
`scorers.py`. No sandbox and no tools: this isolates diagnostic reasoning from investigation,
so a regression here is a reasoning regression and not a flaky MCP call. A companion sandboxed
suite that grades the investigation itself needs seeded `github_*` warehouse data and is not
built yet.

Run:
    hogli evals ci_diagnosis
    hogli evals ci_diagnosis --eval jest_jsdom_performance_now
"""

from __future__ import annotations

import os
import json
from typing import Any

import structlog
from anthropic import AsyncAnthropic

from products.engineering_analytics.evals.cases import CASES
from products.engineering_analytics.evals.scorers import CIAttribution, CIEvidenceGate, CIRootCause, CISymptomNotCause
from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPrivateEval

logger = structlog.get_logger(__name__)

SUITE_KIND = SuiteKind.ONE_SHOT

MODEL = "claude-sonnet-5"

# Structured output, so attribution and the evidence gate are scored by field rather than by
# grepping prose. The framing matches how these arrive in #flakey-tests: someone pastes a
# failing job and asks whose fault it is.
_PROMPT = """You are triaging a CI failure for the PostHog monorepo. An engineer has pasted the
evidence below and wants to know what is going on.

Evidence:
{evidence}

Reply with ONLY a JSON object, no prose or code fences, with exactly these keys:

{{
  "attribution": one of "pr_caused" | "trunk_broken" | "flaky" | "infrastructure",
  "root_cause": "the mechanism, in one or two sentences — why it fails, not what the error says",
  "evidence": "the specific line, count, or observation from the input that supports it",
  "location": "the file, function, or job the problem lives in",
  "proposed_fix": "the narrowest change that would fix it"
}}

Rules:
- Pick exactly one attribution. "pr_caused" means the PR under discussion introduced it;
  "trunk_broken" means master is red and every concurrent PR sees it; "flaky" means the same
  commit both passes and fails; "infrastructure" means runner, network, or registry.
- The loudest error in a log is often not the cause. An error that appears in passing runs as
  well as failing ones did not cause the failure.
- Do not assume the engineer is blameless. Sometimes their PR really did break it.
"""


async def _diagnose(case: BaseEvalCase, ctx: EvalContext) -> dict[str, Any]:
    """One model invocation; its parsed JSON becomes the scorer output.

    Calls Anthropic directly rather than through `get_llm_client`: one-shot suites are the
    one kind the harness does not boot a gateway for (`INFRA_BY_KIND`), which is why their
    preflight requires `LLM_GATEWAY_ANTHROPIC_API_KEY` at all.
    """
    client = AsyncAnthropic(api_key=os.environ["LLM_GATEWAY_ANTHROPIC_API_KEY"])
    response = await client.messages.create(
        model=MODEL,
        messages=[{"role": "user", "content": case.prompt}],
        max_tokens=1024,
    )
    content = "".join(block.text for block in response.content if block.type == "text").strip()
    raw = content
    if content.startswith("```"):
        content = content.strip("`").removeprefix("json").strip()

    try:
        diagnosis = json.loads(content)
    except json.JSONDecodeError:
        # Scored as a miss on every axis rather than raised: a model that cannot hold the output
        # contract is a real regression, and raising here would mark it an infra error and drop
        # the case from the averages entirely.
        logger.warning("ci_diagnosis_unparseable_output", case=case.name)
        return {"diagnosis": None, "raw": raw, "last_message": raw}

    if not isinstance(diagnosis, dict):
        return {"diagnosis": None, "raw": raw, "last_message": raw}

    return {
        "diagnosis": diagnosis,
        "raw": raw,
        "last_message": f"{diagnosis.get('attribution')}: {diagnosis.get('root_cause')}",
    }


async def eval_ci_diagnosis(ctx: EvalContext) -> None:
    cases = [
        BaseEvalCase(
            name=case.name,
            prompt=_PROMPT.format(evidence=case.evidence),
            expected={
                "ci_attribution": {"attribution": case.attribution},
                "ci_root_cause": {"root_cause": case.root_cause},
                "ci_symptom_not_cause": {"decoys": case.decoy},
            },
            metadata={"source": case.source, "attribution": case.attribution},
        )
        for case in CASES
    ]

    await OneShotPrivateEval(
        experiment_name="ci-diagnosis",
        cases=cases,
        scorers=[CIAttribution(), CISymptomNotCause(), CIEvidenceGate(), CIRootCause()],
        task=_diagnose,
        ctx=ctx,
    )
