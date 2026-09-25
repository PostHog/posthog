"""Turn one scout run's session log (tasks-runs-session-logs-retrieve --json, saved to a file) into
the facts the judge and the hard checks need: the pinned commit check, every bash command and the
files it touched, every report the scout filed, every memory write, and the close-out summary.

Usage: python3 parse_run_log.py <session-log.json> [--page page-1.txt] [--commit <sha>] > run.facts.json
"""

from __future__ import annotations

import re
import json
import argparse
from pathlib import Path
from typing import TypedDict

type JsonValue = dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None
PATH_RE = re.compile(r"(?:posthog|ee|products)/[\w./-]+\.py")


class ToolCall(TypedDict):
    id: str
    ts: JsonValue
    title: str
    kind: JsonValue
    input: JsonValue
    output: str


def _object(value: JsonValue) -> dict[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def _text(value: JsonValue) -> str:
    return value if isinstance(value, str) else ""


def _content_text(value: JsonValue, *, nested: bool = False) -> str:
    if not isinstance(value, list):
        return ""
    parts = [_object(part) for part in value]
    if nested:
        parts = [_object(part.get("content")) for part in parts]
    return "".join(_text(part.get("text")) for part in parts)


def tool_calls(entries: list[dict[str, JsonValue]]) -> list[ToolCall]:
    calls: dict[str, ToolCall] = {}
    order: list[str] = []
    for entry in entries:
        notification = _object(entry.get("notification"))
        if notification.get("method") != "session/update":
            continue
        update = _object(_object(notification.get("params")).get("update"))
        kind = update.get("sessionUpdate")
        call_id = update.get("toolCallId")
        if not isinstance(call_id, str):
            continue
        if kind == "tool_call":
            calls[call_id] = {
                "id": call_id,
                "ts": entry.get("timestamp"),
                "title": _text(update.get("title")),
                "kind": update.get("kind"),
                "input": update.get("rawInput"),
                "output": "",
            }
            order.append(call_id)
        elif kind == "tool_call_update" and call_id in calls:
            calls[call_id]["output"] += _content_text(update.get("content"), nested=True)
            calls[call_id]["output"] += _content_text(_object(update.get("rawOutput")).get("content"))
    return [calls[call_id] for call_id in order]


def exec_command(call: ToolCall) -> str:
    return _text(_object(call["input"]).get("command")) or call["title"]


def parse_call_json(cmd: str, tool: str) -> dict[str, JsonValue] | None:
    marker = f"call {tool} "
    index = cmd.find(marker)
    if index < 0:
        return None
    raw = cmd[index + len(marker) :]
    try:
        value: JsonValue = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return value if isinstance(value, dict) else {"_raw": raw}


def facts(entries: list[dict[str, JsonValue]], page: set[str], commit: str | None) -> dict[str, JsonValue]:
    calls = tool_calls(entries)
    bash = [call for call in calls if call["title"].startswith("/bin/bash")]
    pin = next((call for call in bash if "git fetch --depth=1" in exec_command(call)), None)
    pin_ok = bool(commit and pin and commit in pin["output"] and "HEAD is now at" in pin["output"])
    touched: set[str] = set()
    for call in bash:
        touched.update(PATH_RE.findall(exec_command(call)))
    reports: list[JsonValue] = []
    memory: list[JsonValue] = []
    forgets: list[JsonValue] = []
    for call in calls:
        command = exec_command(call)
        if "call scout-emit-report " in command:
            reports.append(
                {
                    "ts": call["ts"],
                    "payload": parse_call_json(command, "scout-emit-report"),
                    "response": call["output"][:600],
                }
            )
        elif "call scout-edit-report " in command:
            reports.append(
                {
                    "ts": call["ts"],
                    "edit": True,
                    "payload": parse_call_json(command, "scout-edit-report"),
                    "response": call["output"][:600],
                }
            )
        elif "call scout-scratchpad-remember " in command:
            payload = parse_call_json(command, "scout-scratchpad-remember") or {}
            memory.append({"ts": call["ts"], "key": payload.get("key"), "content": payload.get("content")})
        elif "call scout-scratchpad-forget " in command:
            payload = parse_call_json(command, "scout-scratchpad-forget") or {}
            forgets.append(payload.get("key"))
    summaries = [
        _object(call["input"]).get("summary")
        for call in calls
        if call["title"].endswith("task_summary_update") and isinstance(call["input"], dict)
    ]
    reads_of_other_copies = sorted(
        {match for call in calls for match in re.findall(r"api-quality-b\d+", exec_command(call) + call["output"])}
    )
    return {
        "tool_calls": len(calls),
        "bash_commands": len(bash),
        "pin_ok": pin_ok,
        "pin_output": pin["output"][:300] if pin else "",
        "files_touched": list[JsonValue](sorted(touched)),
        "files_in_page": list[JsonValue](sorted(touched & page)) if page else None,
        "files_outside_page": list[JsonValue](sorted(touched - page)) if page else None,
        "reports": reports,
        "memory_writes": memory,
        "memory_forgets": forgets,
        "copy_ids_seen": reads_of_other_copies,
        "summaries": summaries,
        "first_ts": entries[0].get("timestamp") if entries else None,
        "last_ts": entries[-1].get("timestamp") if entries else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("log")
    parser.add_argument("--page")
    parser.add_argument("--commit")
    args = parser.parse_args()
    raw_entries: JsonValue = json.loads(Path(args.log).read_text())
    if isinstance(raw_entries, dict):
        raw_entries = raw_entries.get("results") or raw_entries.get("entries") or []
    entries = [_object(entry) for entry in raw_entries] if isinstance(raw_entries, list) else []
    page = set(Path(args.page).read_text().split()) if args.page else set()
    print(json.dumps(facts(entries, page, args.commit), indent=1))  # noqa: T201 — eval script, stdout is the intended output channel


if __name__ == "__main__":
    main()
