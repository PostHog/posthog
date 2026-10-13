import json
import asyncio
import dataclasses
from collections.abc import Callable

import anthropic
from anthropic.types import JSONOutputFormatParam

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.egress.typesafe import JEV_LATEST
from posthog.llm.system_one import NoulAnswer, NoulQuestion
from posthog.llm.system_one_client import (
    SystemOneClient,
    TypeSafeFallback,
    build_system_one_client,
    system_one_configured,
)

from products.mcp_analytics.backend.agent_evals.agent_loop import AgentTrial
from products.mcp_analytics.backend.agent_evals.grading import Grader, Judgment, expected_tools_grader
from products.mcp_analytics.backend.agent_evals.scenarios import Scenario

DEFAULT_JUDGE_MODEL = "claude-sonnet-5-5"
# TypeSafe is approved only for experiments that send no customer data. Run these evals against
# synthetic or PostHog-owned projects.
JEV_FALLBACK = TypeSafeFallback(model=JEV_LATEST, source="mcp_analytics_evals", priority=Priority.BATCH)
JEV_PASS_THRESHOLD = 0.5

JUDGE_INSTRUCTIONS = (
    "You grade whether an AI agent's final answer meets the success criteria for a user's request. "
    "Accept a different reasonable definition of a term when the answer states it explicitly. "
    "Reply with your verdict as JSON."
)
JEV_INSTRUCTIONS = (
    "Does the `answer` complete the `request` and meet the `success_criteria`? "
    "A different reasonable definition of a term is acceptable when the answer states it explicitly."
)
# Structured output, because current Claude models reject a forced tool_choice.
VERDICT_FORMAT: JSONOutputFormatParam = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "passed": {"type": "boolean"},
            "rationale": {"type": "string", "description": "One sentence explaining the verdict."},
        },
        "required": ["passed", "rationale"],
        "additionalProperties": False,
    },
}


class GraderUnavailable(Exception):
    """A grader cannot run on this machine, for example for want of credentials."""


def make_judge(client: anthropic.AsyncAnthropic, model: str) -> Grader:
    async def judge(scenario: Scenario, trial: AgentTrial) -> Judgment:
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=JUDGE_INSTRUCTIONS,
            messages=[{"role": "user", "content": _judge_prompt(scenario, trial)}],
            output_config={"format": VERDICT_FORMAT},
        )
        if response.stop_reason != "end_turn":
            raise ValueError(f"judge stopped with {response.stop_reason}")
        text = next(block.text for block in response.content if block.type == "text")
        parsed = json.loads(text)
        return Judgment(passed=parsed["passed"], score=1.0 if parsed["passed"] else 0.0, rationale=parsed["rationale"])

    return judge


def _judge_prompt(scenario: Scenario, trial: AgentTrial) -> str:
    return (
        f"<request>\n{scenario.intent}\n</request>\n\n"
        f"<success_criteria>\n{scenario.success_criteria}\n</success_criteria>\n\n"
        f"<answer>\n{trial.final_text}\n</answer>"
    )


def make_jev(client: SystemOneClient) -> Grader:
    async def jev(scenario: Scenario, trial: AgentTrial) -> Judgment:
        state = {"request": scenario.intent, "success_criteria": scenario.success_criteria, "answer": trial.final_text}
        # TypeSafe's client is synchronous.
        result = await asyncio.to_thread(
            client.decide, state=state, questions={"passed": NoulQuestion(instructions=JEV_INSTRUCTIONS)}
        )
        answer = result.answers["passed"]
        if not isinstance(answer, NoulAnswer):
            return Judgment(passed=None, score=None, rationale=f"{result.model} declined to answer")
        return Judgment(
            passed=answer.probability >= JEV_PASS_THRESHOLD,
            score=answer.probability,
            rationale=f"{result.model} put the probability of success at {answer.probability:.2f}",
        )

    return jev


@frozen
class GraderSettings:
    anthropic_api_key: str = dataclasses.field(repr=False)
    judge_model: str = DEFAULT_JUDGE_MODEL


def _build_judge(settings: GraderSettings) -> Grader:
    if not settings.anthropic_api_key:
        raise GraderUnavailable("judge needs ANTHROPIC_API_KEY")
    return make_judge(anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key), settings.judge_model)


def _build_jev(settings: GraderSettings) -> Grader:
    if not system_one_configured(JEV_FALLBACK):
        raise GraderUnavailable(
            "jev needs AI_GATEWAY_URL and AI_GATEWAY_API_KEY, or TYPESAFE_API_KEY in local development"
        )
    client = build_system_one_client(model=JEV_LATEST, ai_product="mcp_analytics", typesafe_fallback=JEV_FALLBACK)
    return make_jev(client)


# jev is opt-in by name: TypeSafe may only receive data PostHog owns, so a run asks for it knowingly.
DEFAULT_GRADERS = ("expected_tools", "judge")
GRADERS: dict[str, Callable[[GraderSettings], Grader]] = {
    "expected_tools": lambda _: expected_tools_grader,
    "judge": _build_judge,
    "jev": _build_jev,
}
