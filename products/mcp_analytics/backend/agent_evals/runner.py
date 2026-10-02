import json
import time
import asyncio
import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import anthropic
from anthropic.types import Message, MessageParam, ToolParam
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import AudioContent, CallToolResult, ImageContent, Implementation, TextContent, Tool

from posthog.dataclasses import frozen

from products.mcp_analytics.backend.agent_evals.agent_loop import (
    AgentTrial,
    ToolOutcome,
    TrialDeps,
    TrialUsage,
    run_trial,
)
from products.mcp_analytics.backend.agent_evals.scenarios import Scenario

Effort = Literal["low", "medium", "high", "xhigh", "max"]

SYSTEM_PROMPT = (
    "You are an AI agent connected to an MCP server. "
    "Use the server's tools to complete the user's request, then reply with the answer."
)
MAX_TOKENS = 16_000
TOOL_CALL_TIMEOUT = timedelta(seconds=60)
CLIENT_INFO = Implementation(name="mcp-eval-agent", version="0.0.0")


@frozen
class RunConfig:
    url: str
    headers: dict[str, str] = dataclasses.field(repr=False)
    scenarios: tuple[Scenario, ...]
    trials: int
    concurrency: int
    model: str
    effort: Effort
    max_turns: int


@frozen
class AgentRunReport:
    server_url: str
    headers: dict[str, str]
    tool_names: tuple[str, ...]
    model: str
    effort: Effort
    system_prompt: str
    trials_per_scenario: int
    rounds_completed: int
    max_turns: int
    max_tokens: int
    started_at: str
    finished_at: str
    trials: tuple[AgentTrial, ...]
    error: str | None

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self), indent=2)


async def run_agent_evals(config: RunConfig, client: anthropic.AsyncAnthropic) -> AgentRunReport:
    started_at = _now_iso()
    async with _mcp_session(config) as catalog:
        tools = await _list_all_tools(catalog)
    tool_params: list[ToolParam] = [
        {"name": tool.name, "description": tool.description or "", "input_schema": tool.inputSchema} for tool in tools
    ]
    slots = asyncio.Semaphore(config.concurrency)

    async def bounded(scenario: Scenario, trial: int) -> AgentTrial:
        async with slots:
            return await _run_scenario(config, client, tool_params, scenario, trial)

    trials: list[AgentTrial] = []
    rounds_completed = 0
    error: str | None = None
    try:
        # Rounds run in sequence and scenarios run concurrently inside a round. Scenarios that
        # change server state share it, so they can race each other and leave state for the next round.
        for trial in range(1, config.trials + 1):
            trials.extend(await asyncio.gather(*(bounded(scenario, trial) for scenario in config.scenarios)))
            rounds_completed = trial
    except Exception as aborted:
        error = str(aborted)

    return AgentRunReport(
        server_url=_without_credentials(config.url),
        headers={name: value for name, value in config.headers.items() if name.lower() != "authorization"},
        tool_names=tuple(tool.name for tool in tools),
        model=config.model,
        effort=config.effort,
        system_prompt=SYSTEM_PROMPT,
        trials_per_scenario=config.trials,
        rounds_completed=rounds_completed,
        max_turns=config.max_turns,
        max_tokens=MAX_TOKENS,
        started_at=started_at,
        finished_at=_now_iso(),
        trials=tuple(trials),
        error=error,
    )


async def _run_scenario(
    config: RunConfig,
    client: anthropic.AsyncAnthropic,
    tools: list[ToolParam],
    scenario: Scenario,
    trial: int,
) -> AgentTrial:
    async def create_message(messages: list[MessageParam]) -> Message:
        return await client.messages.create(
            model=config.model,
            max_tokens=MAX_TOKENS,
            # A breakpoint on the system block caches the tools and system prompt, which every
            # scenario shares. The top-level breakpoint only covers one conversation, because it
            # lands on the latest message and each scenario starts from a different intent.
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=tools,
            messages=messages,
            output_config={"effort": config.effort},
            extra_body={"cache_control": {"type": "ephemeral"}},
        )

    opened = False
    try:
        # A session per trial, so state a server keeps per session cannot leak between trials.
        async with _mcp_session(config) as session:
            opened = True

            async def call_tool(name: str, tool_input: object) -> ToolOutcome:
                arguments = tool_input if isinstance(tool_input, dict) else {}
                result = await session.call_tool(name, arguments, read_timeout_seconds=TOOL_CALL_TIMEOUT)
                return ToolOutcome(text=tool_result_text(result), is_error=bool(result.isError))

            deps = TrialDeps(create_message=create_message, call_tool=call_tool, now_ms=_now_ms)
            return await run_trial(scenario, trial, config.max_turns, deps)
    except Exception as error:
        if opened:
            raise
        return AgentTrial(
            scenario_id=scenario.id,
            trial=trial,
            outcome="mcp_error",
            final_text="",
            tool_calls=(),
            turns=0,
            usage=TrialUsage(),
            duration_ms=0,
            error=str(error),
        )


@asynccontextmanager
async def _mcp_session(config: RunConfig) -> AsyncIterator[ClientSession]:
    async with streamablehttp_client(config.url, headers=config.headers) as (read, write, _):
        async with ClientSession(read, write, client_info=CLIENT_INFO) as session:
            await session.initialize()
            yield session


async def _list_all_tools(session: ClientSession) -> list[Tool]:
    tools: list[Tool] = []
    cursor: str | None = None
    while True:
        page = await session.list_tools(cursor=cursor)
        tools.extend(page.tools)
        cursor = page.nextCursor
        if not cursor:
            return tools


def tool_result_text(result: CallToolResult) -> str:
    parts: list[str] = []
    for item in result.content:
        match item:
            case TextContent():
                parts.append(item.text)
            case ImageContent() | AudioContent():
                parts.append(f"[{item.type} {item.mimeType}, {len(item.data)} base64 characters]")
            case _:
                parts.append(item.model_dump_json())
    if not parts and result.structuredContent:
        parts.append(json.dumps(result.structuredContent))
    return "\n".join(parts)


def format_run_summary(report: AgentRunReport) -> str:
    by_scenario: dict[str, list[AgentTrial]] = {}
    for trial in report.trials:
        by_scenario.setdefault(trial.scenario_id, []).append(trial)
    answered = sum(1 for trial in report.trials if trial.outcome == "answered")
    lines = [
        f"agent run on {report.server_url}: {report.model} ({report.effort}), "
        f"{len(by_scenario)} scenarios x {report.rounds_completed}/{report.trials_per_scenario} rounds",
        f"answered {answered}/{len(report.trials)}",
    ]
    for scenario_id, trials in by_scenario.items():
        tool_errors = sum(1 for trial in trials for call in trial.tool_calls if call.is_error)
        suffix = f" ({tool_errors} tool errors)" if tool_errors else ""
        lines.append(f"  {scenario_id}: {' '.join(trial.outcome for trial in trials)}{suffix}")
    if report.error:
        lines.append(f"aborted: {report.error}")
    return "\n".join(lines)


def _without_credentials(url: str) -> str:
    parts = urlsplit(url)
    host = f"{parts.hostname or ''}:{parts.port}" if parts.port else parts.hostname or ""
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def _now_ms() -> int:
    return time.monotonic_ns() // 1_000_000


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
