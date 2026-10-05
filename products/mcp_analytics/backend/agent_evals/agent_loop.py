import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

import anthropic
from anthropic.types import Message, MessageParam, ToolResultBlockParam, ToolUseBlock, Usage

from posthog.dataclasses import frozen

from products.mcp_analytics.backend.agent_evals.scenarios import Scenario

TrialOutcome = Literal[
    "answered",
    "turn_limit",  # still calling tools after max_turns model responses
    "truncated",  # a response hit max_tokens
    "refused",
    "model_error",  # the API call failed, or returned a stop reason the loop cannot continue from
    "mcp_error",  # the MCP session could not be opened
]

_STOP_REASON_OUTCOMES: dict[str, TrialOutcome] = {
    "end_turn": "answered",
    "stop_sequence": "answered",
    "max_tokens": "truncated",
    "refusal": "refused",
}


@frozen
class ToolCallRecord:
    name: str
    input: object
    is_error: bool
    # Kept whole, because a judge that reads a shortened result grades a different trial.
    result_text: str
    latency_ms: int


@frozen
class TrialUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def add(self, usage: Usage) -> "TrialUsage":
        return TrialUsage(
            input_tokens=self.input_tokens + usage.input_tokens,
            output_tokens=self.output_tokens + usage.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + (usage.cache_read_input_tokens or 0),
            cache_creation_input_tokens=self.cache_creation_input_tokens + (usage.cache_creation_input_tokens or 0),
        )


@frozen
class AgentTrial:
    scenario_id: str
    trial: int
    outcome: TrialOutcome
    final_text: str
    tool_calls: tuple[ToolCallRecord, ...]
    turns: int
    usage: TrialUsage
    duration_ms: int
    error: str | None = None


@frozen
class ToolOutcome:
    text: str
    is_error: bool


@frozen
class TrialDeps:
    create_message: Callable[[list[MessageParam]], Awaitable[Message]]
    call_tool: Callable[[str, object], Awaitable[ToolOutcome]]
    now_ms: Callable[[], int]


async def run_trial(scenario: Scenario, trial: int, max_turns: int, deps: TrialDeps) -> AgentTrial:
    started_at = deps.now_ms()
    messages: list[MessageParam] = [{"role": "user", "content": scenario.intent}]
    tool_calls: list[ToolCallRecord] = []
    usage = TrialUsage()
    turns = 0
    last_text = ""

    def finish(outcome: TrialOutcome, error: str | None = None) -> AgentTrial:
        return AgentTrial(
            scenario_id=scenario.id,
            trial=trial,
            outcome=outcome,
            final_text=last_text,
            tool_calls=tuple(tool_calls),
            turns=turns,
            usage=usage,
            duration_ms=deps.now_ms() - started_at,
            error=error,
        )

    while turns < max_turns:
        try:
            response = await deps.create_message(messages)
        except anthropic.APIError as error:
            return finish("model_error", str(error))
        turns += 1
        usage = usage.add(response.usage)
        last_text = "\n".join(block.text for block in response.content if block.type == "text")
        # Append the whole content, thinking blocks included, so the history stays append-only.
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            outcome = _STOP_REASON_OUTCOMES.get(response.stop_reason or "")
            return (
                finish(outcome) if outcome else finish("model_error", f"unexpected stop_reason {response.stop_reason}")
            )

        tool_uses = [block for block in response.content if isinstance(block, ToolUseBlock)]
        records = await asyncio.gather(*(_call_recorded(deps, use) for use in tool_uses))
        tool_calls.extend(records)
        # Every result goes back in one user message. Split messages teach the model to stop calling tools in parallel.
        results: list[ToolResultBlockParam] = [
            {"type": "tool_result", "tool_use_id": use.id, "content": record.result_text, "is_error": record.is_error}
            for use, record in zip(tool_uses, records, strict=True)
        ]
        messages.append({"role": "user", "content": results})
    return finish("turn_limit")


async def _call_recorded(deps: TrialDeps, use: ToolUseBlock) -> ToolCallRecord:
    started_at = deps.now_ms()
    try:
        outcome = await deps.call_tool(use.name, use.input)
    except Exception as error:
        # A transport failure is something the agent sees and can recover from, so it is
        # fed back as an error result rather than ending the trial.
        outcome = ToolOutcome(text=str(error), is_error=True)
    return ToolCallRecord(
        name=use.name,
        input=use.input,
        is_error=outcome.is_error,
        result_text=outcome.text,
        latency_ms=deps.now_ms() - started_at,
    )
