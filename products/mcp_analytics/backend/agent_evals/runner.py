import re
import json
import time
import asyncio
import logging
import dataclasses
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit

import anthropic
from anthropic.types import Message, MessageParam, TextBlockParam, ToolParam
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

# The levels the pinned anthropic SDK types. It predates `xhigh`.
Effort = Literal["low", "medium", "high", "max"]

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
    effort: Effort | None
    max_turns: int


@frozen
class AgentRunReport:
    # The origin only: a path can carry a capability token, and the report is shared.
    server_origin: str
    # Names only, because any header can carry a credential on a server we don't know.
    header_names: tuple[str, ...]
    tool_names: tuple[str, ...]
    # The scenarios as they ran, so a later grader never reads criteria that were edited afterwards.
    scenarios: tuple[Scenario, ...]
    model: str
    effort: Effort | None
    system_prompt: str
    trials_per_scenario: int
    max_turns: int
    max_tokens: int
    started_at: str
    finished_at: str
    trials: tuple[AgentTrial, ...]

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self), indent=2, default=lambda scenario: scenario.model_dump())


async def run_agent_evals(config: RunConfig, client: anthropic.AsyncAnthropic) -> AgentRunReport:
    started_at = _now_iso()
    async with _mcp_session(config) as (catalog, server_instructions):
        tools = await _list_all_tools(catalog)
    # MCP clients pass the server's instructions to the model, so the eval agent gets them too.
    system_prompt = f"{SYSTEM_PROMPT}\n\n{server_instructions}" if server_instructions else SYSTEM_PROMPT
    # A breakpoint on the system block caches the tools and system prompt, which every scenario
    # shares. The top-level breakpoint only covers one conversation, because it lands on the latest
    # message and each scenario starts from a different intent.
    system: list[TextBlockParam] = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
    tool_params: list[ToolParam] = [
        {"name": tool.name, "description": tool.description or "", "input_schema": tool.inputSchema} for tool in tools
    ]
    slots = asyncio.Semaphore(config.concurrency)

    async def bounded(scenario: Scenario, trial: int) -> AgentTrial:
        async with slots:
            return await _run_scenario(config, client, system, tool_params, scenario, trial)

    trials: list[AgentTrial] = []
    # Rounds run in sequence and scenarios run concurrently inside a round. Scenarios that
    # change server state share it, so they can race each other and leave state for the next round.
    for trial in range(1, config.trials + 1):
        trials.extend(await asyncio.gather(*(bounded(scenario, trial) for scenario in config.scenarios)))

    return AgentRunReport(
        server_origin=server_origin(config.url),
        header_names=tuple(config.headers),
        tool_names=tuple(tool.name for tool in tools),
        scenarios=config.scenarios,
        model=config.model,
        effort=config.effort,
        system_prompt=system_prompt,
        trials_per_scenario=config.trials,
        max_turns=config.max_turns,
        max_tokens=MAX_TOKENS,
        started_at=started_at,
        finished_at=_now_iso(),
        trials=tuple(trials),
    )


async def _run_scenario(
    config: RunConfig,
    client: anthropic.AsyncAnthropic,
    system: list[TextBlockParam],
    tools: list[ToolParam],
    scenario: Scenario,
    trial: int,
) -> AgentTrial:
    async def create_message(messages: list[MessageParam]) -> Message:
        # Streaming, because the SDK refuses MAX_TOKENS without it for models with a lower non-streaming cap.
        async with client.messages.stream(
            model=config.model,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=tools,
            messages=messages,
            # Omitted unless chosen, because models without effort support reject the field.
            output_config={"effort": config.effort} if config.effort else anthropic.omit,
            extra_body={"cache_control": {"type": "ephemeral"}},
        ) as stream:
            return await stream.get_final_message()

    finished: AgentTrial | None = None
    try:
        # A session per trial, so state a server keeps per session cannot leak between trials.
        async with _mcp_session(config) as (session, _):
            # MCP clients list tools in each session; the SDK validates tool results against that list.
            await _list_all_tools(session)

            async def call_tool(name: str, tool_input: object) -> ToolOutcome:
                if not isinstance(tool_input, dict):
                    return ToolOutcome(text="Tool input must be a JSON object.", is_error=True)
                try:
                    result = await session.call_tool(name, tool_input, read_timeout_seconds=TOOL_CALL_TIMEOUT)
                except Exception as error:
                    return ToolOutcome(text=describe_failure(error, config), is_error=True)
                return ToolOutcome(text=tool_result_text(result), is_error=bool(result.isError))

            deps = TrialDeps(create_message=create_message, call_tool=call_tool, now_ms=_now_ms)
            finished = await run_trial(scenario, trial, config.max_turns, deps)
    except Exception as error:
        if finished is None:
            return AgentTrial(
                scenario_id=scenario.id,
                trial=trial,
                outcome="mcp_error",
                final_text="",
                tool_calls=(),
                turns=0,
                usage=TrialUsage(),
                duration_ms=0,
                error=describe_failure(error, config),
            )
    assert finished is not None
    return finished


def describe_failure(error: Exception, config: RunConfig) -> str:
    # HTTP errors quote the request URL in their own normalized form, and a rejected header's value,
    # so every URL is cut to its origin rather than matched against the configured one.
    text = _URL.sub(lambda match: server_origin(match.group(0)), _describe(error))
    for value in config.headers.values():
        if value:
            text = text.replace(value, "[redacted]")
    return text


def _describe(error: Exception) -> str:
    # anyio task groups wrap the transport's failure, and the group's own message names none of it.
    if isinstance(error, BaseExceptionGroup):
        return "; ".join(
            _describe(inner) if isinstance(inner, Exception) else repr(inner) for inner in error.exceptions
        )
    return str(error) or type(error).__name__


@asynccontextmanager
async def _mcp_session(config: RunConfig) -> AsyncIterator[tuple[ClientSession, str | None]]:
    # Bounds every transport request, including the DELETE that ends the session on close.
    async with streamablehttp_client(
        config.url, headers=config.headers, timeout=TOOL_CALL_TIMEOUT, sse_read_timeout=TOOL_CALL_TIMEOUT
    ) as (read, write, _):
        # The timeout bounds a server that keeps the stream open but never answers initialize or list_tools.
        async with ClientSession(
            read, write, client_info=CLIENT_INFO, read_timeout_seconds=TOOL_CALL_TIMEOUT
        ) as session:
            initialized = await session.initialize()
            yield session, initialized.instructions


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
        f"agent run on {report.server_origin}: {report.model} ({report.effort or 'default effort'}), "
        f"{len(by_scenario)} scenarios x {report.trials_per_scenario} trials",
        f"answered {answered}/{len(report.trials)}",
    ]
    for scenario_id, trials in by_scenario.items():
        tool_errors = sum(1 for trial in trials for call in trial.tool_calls if call.is_error)
        suffix = f" ({tool_errors} tool errors)" if tool_errors else ""
        lines.append(f"  {scenario_id}: {' '.join(trial.outcome for trial in trials)}{suffix}")
    return "\n".join(lines)


@contextmanager
def quiet_transport_logs() -> Iterator[None]:
    """The MCP SDK and httpx log request URLs and tracebacks; the report already records every failure."""
    loggers = [logging.getLogger(name) for name in ("mcp", "httpx", "httpcore")]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.CRITICAL + 1)
    try:
        yield
    finally:
        for logger, level in zip(loggers, levels, strict=True):
            logger.setLevel(level)


_URL = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)


def server_origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}"


def _now_ms() -> int:
    return time.monotonic_ns() // 1_000_000


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
