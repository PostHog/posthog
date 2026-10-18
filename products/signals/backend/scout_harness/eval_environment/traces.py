from __future__ import annotations

import re
import json
import shlex
from collections.abc import Collection, Iterator
from datetime import datetime
from pathlib import Path

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


def load_trace_inputs(run_directory: Path, *, read_tools: Collection[str]) -> TraceInputs:
    """Extract completed reads before the first write, without reading result files."""
    observations: list[TraceObservation] = []
    local_file_reads: list[TraceObservation] = []
    pending: dict[str, TraceObservation] = {}
    first_write_index = None
    for index, event in enumerate(_events(run_directory)):
        notification = _object(event.get("notification"))
        update = _object(_object(notification.get("params")).get("update"))
        call_id = update.get("toolCallId")
        if not isinstance(call_id, str):
            continue
        kind = update.get("sessionUpdate")
        if kind == "tool_call":
            raw_input = _object(update.get("rawInput"))
            command = raw_input.get("command")
            title = update.get("title")
            if isinstance(command, str):
                match = re.fullmatch(r"call\s+([\w:-]+)\s*(.*)", command, re.DOTALL)
                if match is None:
                    if command.split(maxsplit=1)[0:1] in (["search"], ["info"], ["schema"], ["tools"], ["learn"]):
                        continue
                    first_write_index = index
                    break
                tool, payload = match.groups()
                if tool not in read_tools:
                    first_write_index = index
                    break
                arguments = _object(json.loads(payload or "{}"))
            elif isinstance(title, str) and title.startswith("/bin/bash "):
                # Keep only literal cat reads of installed skill files, never shell output generally.
                words = shlex.split(title)
                if len(words) != 3 or words[1] != "-lc":
                    first_write_index = index
                    break
                shell_words = shlex.split(words[2])
                if (
                    not shell_words
                    or shell_words[0] != "cat"
                    or any(
                        not path.startswith("/") or "/skills/" not in path or not path.endswith(".md")
                        for path in shell_words[1:]
                    )
                ):
                    first_write_index = index
                    break
                tool = "local-skill-read"
                paths: list[JsonValue] = list(shell_words[1:])
                arguments = {"paths": paths}
            else:
                first_write_index = index
                break
            timestamp = event.get("timestamp")
            if not isinstance(timestamp, str):
                raise ValueError("Trace tool calls need a timestamp.")
            pending[call_id] = TraceObservation(
                event_index=index,
                timestamp=datetime.fromisoformat(timestamp),
                tool=tool,
                arguments=arguments,
                text="",
            )
        elif kind == "tool_call_update" and update.get("status") == "completed" and call_id in pending:
            call = pending.pop(call_id)
            raw_output = _object(update.get("rawOutput"))
            text = _text_blocks(raw_output.get("content")) or _text_blocks(update.get("content"))
            observation = TraceObservation(
                event_index=call.event_index,
                timestamp=call.timestamp,
                tool=call.tool,
                arguments=call.arguments,
                text=text,
            )
            (local_file_reads if call.tool == "local-skill-read" else observations).append(observation)
    return TraceInputs(
        observations=sorted(observations, key=lambda observation: observation.event_index),
        first_write_index=first_write_index,
        local_file_reads=sorted(local_file_reads, key=lambda observation: observation.event_index),
    )
