from __future__ import annotations

import re
import json
import shlex
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from posthog.dataclasses import frozen


@frozen
class TraceObservation:
    event_index: int
    timestamp: datetime
    tool: str
    arguments: dict[str, JsonValue]
    text: str


@frozen
class TraceInputs:
    observations: list[TraceObservation]
    first_write_index: int | None
    local_file_reads: list[TraceObservation]


def _object(value: object) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        return {}
    return value


def _text_blocks(value: object) -> str:
    if not isinstance(value, list):
        return ""
    texts: list[str] = []
    for block in value:
        item = _object(block)
        text = item.get("text")
        if item.get("type") == "text" and isinstance(text, str):
            texts.append(text)
        elif item.get("type") == "content":
            text = _object(item.get("content")).get("text")
            if isinstance(text, str):
                texts.append(text)
    return "\n".join(texts)


def _events(run_directory: Path) -> Iterator[dict[str, JsonValue]]:
    page_index = json.loads((run_directory / "log-pages.json").read_text())
    offset = 0
    for page in page_index["pages"]:
        if page["first_event_index"] != offset:
            raise ValueError("Trace pages must be contiguous and ordered.")
        relative = Path(page["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Trace page paths must remain inside the run directory.")
        # Exports may prefix page paths with the archive's runs/<id>/ directory.
        path = run_directory / "logs" / relative.name
        if not path.resolve().is_relative_to(run_directory.resolve()):
            raise ValueError("Trace page paths must remain inside the run directory.")
        events = json.loads(path.read_text())
        if len(events) != page["returned"]:
            raise ValueError("Trace page length does not match its index.")
        for event in events:
            yield _object(event)
        offset += len(events)
    if offset != page_index["total_events"]:
        raise ValueError("Trace event count does not match its index.")


@dataclass(frozen=False)
class _ToolCall:
    event_index: int
    timestamp: JsonValue
    raw_input: dict[str, JsonValue]
    title: JsonValue
    completed_index: int | None = None
    text: str = ""


@frozen
class _Read:
    tool: str
    arguments: dict[str, JsonValue]


def _classify(call: _ToolCall, read_tools: Collection[str]) -> _Read | Literal["write", "discovery"]:
    command = call.raw_input.get("command")
    title = call.title
    if isinstance(command, str):
        command = command.strip()
        # Mirrors the exec parser, which consumes `--json` and `--confirm` before the tool name.
        match = re.fullmatch(r"call(?:\s+--(?:json|confirm))*\s+([\w:-]+)\s*(.*)", command, re.DOTALL)
        if match is None:
            if command.split(maxsplit=1)[0:1] in (["search"], ["info"], ["schema"], ["tools"], ["learn"]):
                return "discovery"
            return "write"
        tool, payload = match.groups()
        if tool not in read_tools:
            return "write"
        try:
            arguments = json.loads(payload or "{}")
        except json.JSONDecodeError:
            # Exec rejects invalid JSON before it calls the tool, so the call neither reads nor writes.
            return "discovery"
        return _Read(tool=tool, arguments=_object(arguments))
    if isinstance(title, str) and title.startswith("/bin/bash "):
        # Keep only literal cat reads of installed skill files, never shell output generally.
        words = shlex.split(title)
        if len(words) != 3 or words[1] != "-lc":
            return "write"
        shell_words = shlex.split(words[2])
        if (
            not shell_words
            or shell_words[0] != "cat"
            or any(
                not path.startswith("/") or "/skills/" not in path or not path.endswith(".md")
                for path in shell_words[1:]
            )
        ):
            return "write"
        paths: list[JsonValue] = list(shell_words[1:])
        return _Read(tool="local-skill-read", arguments={"paths": paths})
    return "write"


def load_trace_inputs(run_directory: Path, *, read_tools: Collection[str]) -> TraceInputs:
    """Extract completed reads before the first write, without reading result files."""
    calls: dict[str, _ToolCall] = {}
    for index, event in enumerate(_events(run_directory)):
        notification = _object(event.get("notification"))
        update = _object(_object(notification.get("params")).get("update"))
        call_id = update.get("toolCallId")
        if not isinstance(call_id, str):
            continue
        kind = update.get("sessionUpdate")
        if kind == "tool_call" and call_id not in calls:
            calls[call_id] = _ToolCall(event_index=index, timestamp=event.get("timestamp"), raw_input={}, title=None)
        elif kind != "tool_call_update" or call_id not in calls:
            continue
        # Claude streams arguments: the opening call carries empty input and later updates carry the rest.
        call = calls[call_id]
        raw_input = _object(update.get("rawInput"))
        if raw_input:
            call.raw_input = raw_input
        title = update.get("title")
        if isinstance(title, str):
            call.title = title
        if update.get("status") == "completed" and call.completed_index is None:
            raw_output = _object(update.get("rawOutput"))
            call.completed_index = index
            call.text = _text_blocks(raw_output.get("content")) or _text_blocks(update.get("content"))

    first_write_index = None
    reads: list[tuple[_ToolCall, _Read]] = []
    for call in calls.values():
        classified = _classify(call, read_tools)
        if classified == "discovery":
            continue
        if classified == "write":
            first_write_index = call.event_index
            break
        reads.append((call, classified))

    observations: list[TraceObservation] = []
    local_file_reads: list[TraceObservation] = []
    for call, read in reads:
        if call.completed_index is None:
            continue
        if first_write_index is not None and call.completed_index > first_write_index:
            continue
        if not isinstance(call.timestamp, str):
            raise ValueError("Trace tool calls need a timestamp.")
        observation = TraceObservation(
            event_index=call.event_index,
            timestamp=datetime.fromisoformat(call.timestamp),
            tool=read.tool,
            arguments=read.arguments,
            text=call.text,
        )
        (local_file_reads if read.tool == "local-skill-read" else observations).append(observation)
    return TraceInputs(
        observations=observations,
        first_write_index=first_write_index,
        local_file_reads=local_file_reads,
    )
