"""The ordered tool chain of one sandboxed case.

Scorers, judges, the local log sink, and the run metadata all read the chain from here, so one
chain looks the same wherever someone compares it: across surfaces, runtimes, models, and runs.

Pure data layer, like ``log_parser``: no Braintrust, PostHog, or model dependency.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from .log_parser import EXECUTE_SQL_TOOL_NAME, LogParser, ToolCall, is_answer_query_tool, is_schema_discovery_call

DIGEST_CHAR_LIMIT = 240
JUDGE_CHAIN_STEP_LIMIT = 80
DISCOVERY_TOOL_NAMES = frozenset({"read-data-schema", "metric-list", "metric-describe"})


class ToolChainStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    sequence: int
    """Zero-based position in the chain."""

    turn: int | None
    """Zero-based conversation turn the call belongs to. Single-turn cases are all turn 0.
    ``None`` in a multi-turn case when the runner could not slice the log into turns."""

    name: str
    """Normalized tool name, with ``exec`` unwrapped to the inner tool."""

    raw_name: str
    server: str | None
    is_error: bool
    is_discovery: bool = False
    """Catalog or schema lookup, classified from the full input before the digest truncates it."""

    input_digest: str
    output_digest: str
    started_at: str
    ended_at: str
    duration_seconds: float | None


def build_tool_chain(output: dict[str, Any] | None) -> list[ToolChainStep]:
    """Build the chain from a sandboxed case's scorer ``output``.

    Reads ``raw_log`` and ``prompt``, plus ``turn_logs`` and ``turn_prompts`` for a multi-turn case.
    """
    if not output or not output.get("raw_log"):
        return []
    parser = LogParser.cached(output["raw_log"], initial_prompt=output.get("prompt", "") or "")
    turn_logs = output.get("turn_logs")
    turn_prompts = output.get("turn_prompts")
    multi_turn = isinstance(turn_logs, list) or (isinstance(turn_prompts, list) and len(turn_prompts) > 1)
    turns = _turn_by_call_id(turn_logs)
    return [
        ToolChainStep(
            sequence=call.sequence,
            turn=turns.get(call.call_id) if multi_turn else 0,
            name=call.name,
            raw_name=call.raw_name,
            server=call.server,
            is_error=call.is_error,
            is_discovery=call.name in DISCOVERY_TOOL_NAMES or is_schema_discovery_call(call),
            input_digest=input_digest(call),
            output_digest=_truncate(_collapse(call.output)),
            started_at=call.started_at,
            ended_at=call.ended_at,
            duration_seconds=_duration_seconds(call.started_at, call.ended_at),
        )
        for call in parser.get_tool_calls(include_skills=True)
    ]


def is_answer_step(step: ToolChainStep) -> bool:
    return is_answer_query_tool(step.name) and not step.is_discovery


def summarize_tool_chain(chain: list[ToolChainStep]) -> dict[str, Any]:
    """Counts that compare chains across runs without reading every step."""
    first_answer = next((step.sequence for step in chain if is_answer_step(step) and not step.is_error), None)
    return {
        "tool_count": len(chain),
        "distinct_tools": sorted({step.name for step in chain}),
        "discovery_calls": sum(1 for step in chain if step.is_discovery),
        "answer_calls": sum(1 for step in chain if is_answer_step(step)),
        "errors": sum(1 for step in chain if step.is_error),
        "first_answer_sequence": first_answer,
        "servers": sorted({step.server for step in chain if step.server}),
    }


def render_tool_chain(chain: list[ToolChainStep], *, step_limit: int = JUDGE_CHAIN_STEP_LIMIT) -> str:
    """Render the chain as numbered lines for a judge prompt: ``n. tool(input) -> output``."""
    if not chain:
        return "(no tool calls)"
    lines = []
    for step in chain[:step_limit]:
        result = f"ERROR {step.output_digest}" if step.is_error else step.output_digest
        lines.append(f"{step.sequence + 1}. {step.name}({step.input_digest}) -> {result}")
    if len(chain) > step_limit:
        lines.append(f"... {len(chain) - step_limit} more calls")
    return "\n".join(lines)


def input_digest(call: ToolCall) -> str:
    if call.name == EXECUTE_SQL_TOOL_NAME:
        query = call.input.get("query")
        if isinstance(query, str):
            return _truncate(_collapse(query))
    return _truncate(json.dumps(call.input, sort_keys=True, default=str, separators=(",", ":")))


def _turn_by_call_id(turn_logs: Any) -> dict[str, int]:
    turns: dict[str, int] = {}
    if not isinstance(turn_logs, list):
        return turns
    for turn, turn_log in enumerate(turn_logs):
        if not isinstance(turn_log, str):
            continue
        for line in turn_log.splitlines():
            call_id = _tool_call_id(line)
            if call_id is not None:
                turns.setdefault(call_id, turn)
    return turns


def _tool_call_id(line: str) -> str | None:
    if '"tool_call"' not in line:
        return None
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        return None
    notification = entry.get("notification") if isinstance(entry, dict) else None
    params = notification.get("params") if isinstance(notification, dict) else None
    update = params.get("update") if isinstance(params, dict) else None
    if not isinstance(update, dict) or update.get("sessionUpdate") != "tool_call":
        return None
    call_id = update.get("toolCallId")
    return call_id if isinstance(call_id, str) else None


def _duration_seconds(started_at: str, ended_at: str) -> float | None:
    start = _parse_timestamp(started_at)
    end = _parse_timestamp(ended_at)
    if start is None or end is None:
        return None
    return round((end - start).total_seconds(), 3)


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _truncate(text: str) -> str:
    return text if len(text) <= DIGEST_CHAR_LIMIT else text[: DIGEST_CHAR_LIMIT - 1] + "…"
