import asyncio
import dataclasses
from collections.abc import Callable

import anthropic
from anthropic.types import ToolChoiceToolParam, ToolParam, ToolUseBlock

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.egress.typesafe import JEV_LATEST
from posthog.egress.typesafe.transport import TypeSafeEgressBudgetExhausted
from posthog.llm.system_one import NoulAnswer, NoulQuestion, SystemOneNotConfigured, SystemOneRequestFailed
from posthog.llm.system_one_client import (
    SystemOneClient,
    TypeSafeFallback,
    build_system_one_client,
    system_one_configured,
)

from products.mcp_analytics.backend.agent_evals.agent_loop import AgentTrial
from products.mcp_analytics.backend.agent_evals.grading import Grader, Verdict, expected_tools_grader, verdict
from products.mcp_analytics.backend.agent_evals.scenarios import Scenario

DEFAULT_JUDGE_MODEL = "claude-sonnet-5-5"
# TypeSafe is approved only for experiments that send no customer data. Run these evals against
# synthetic or PostHog-owned projects.
JEV_FALLBACK = TypeSafeFallback(model=JEV_LATEST, source="mcp_analytics_evals", priority=Priority.BATCH)
JEV_PASS_THRESHOLD = 0.5

JUDGE_INSTRUCTIONS = (
    "You grade whether an AI agent's final answer meets the success criteria for a user's request. "
    "Accept a different reasonable definition of a term when the answer states it explicitly. "
    "Record your verdict with the record_verdict tool."
)
JEV_INSTRUCTIONS = (
    "Does the `answer` complete the `request` and meet the `success_criteria`? "
    "A different reasonable definition of a term is acceptable when the answer states it explicitly."
)
VERDICT_TOOL: ToolParam = {
    "name": "record_verdict",
    "description": "Record whether the answer meets the success criteria.",
    "input_schema": {
        "type": "object",
        "properties": {
            "passed": {"type": "boolean"},
            "rationale": {"type": "string", "description": "One sentence explaining the verdict."},
        },
        "required": ["passed", "rationale"],
    },
}
FORCE_VERDICT: ToolChoiceToolParam = {"type": "tool", "name": VERDICT_TOOL["name"]}


class GraderUnavailable(Exception):
    """A grader cannot run on this machine, for example for want of credentials."""


def make_judge(client: anthropic.AsyncAnthropic, model: str) -> Grader:
    async def judge(scenario: Scenario, trial: AgentTrial) -> Verdict:
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=1024,
                system=JUDGE_INSTRUCTIONS,
                tools=[VERDICT_TOOL],
                tool_choice=FORCE_VERDICT,
                messages=[{"role": "user", "content": _judge_prompt(scenario, trial)}],
            )
        except anthropic.APIError as error:
            return verdict("judge", None, None, f"judge call failed: {error}")
        for block in response.content:
            if isinstance(block, ToolUseBlock) and isinstance(block.input, dict):
                passed = bool(block.input.get("passed"))
                return verdict("judge", passed, 1.0 if passed else 0.0, str(block.input.get("rationale", "")))
        return verdict("judge", None, None, "judge did not record a verdict")

    return judge


def _judge_prompt(scenario: Scenario, trial: AgentTrial) -> str:
    return (
        f"<request>\n{scenario.intent}\n</request>\n\n"
        f"<success_criteria>\n{scenario.success_criteria}\n</success_criteria>\n\n"
        f"<answer>\n{trial.final_text}\n</answer>"
    )


def make_jev(client: SystemOneClient) -> Grader:
    async def jev(scenario: Scenario, trial: AgentTrial) -> Verdict:
        state = {"request": scenario.intent, "success_criteria": scenario.success_criteria, "answer": trial.final_text}
        try:
            result = await asyncio.to_thread(
                client.decide, state=state, questions={"passed": NoulQuestion(instructions=JEV_INSTRUCTIONS)}
            )
        except (SystemOneRequestFailed, SystemOneNotConfigured, TypeSafeEgressBudgetExhausted) as error:
            return verdict("jev", None, None, f"jev call failed: {error}")
        answer = result.answers["passed"]
        if not isinstance(answer, NoulAnswer):
            return verdict("jev", None, None, "jev declined to answer")
        passed = answer.probability >= JEV_PASS_THRESHOLD
        return verdict(
            "jev", passed, answer.probability, f"jev put the probability of success at {answer.probability:.2f}"
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


GRADERS: dict[str, Callable[[GraderSettings], Grader]] = {
    "expected_tools": lambda _: expected_tools_grader,
    "judge": _build_judge,
    "jev": _build_jev,
}
