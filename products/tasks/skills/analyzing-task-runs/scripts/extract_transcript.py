#!/usr/bin/env python3
"""Extract a compact transcript from a task-run log (JSONL/NDJSON).

Usage:
    python3 extract_transcript.py <run-log.jsonl> > transcript.md

Reads the durable run log one line at a time and emits only the parts an
efficiency analysis needs: ordered tool calls (kind + title), their final
statuses, and user/agent messages. Streaming status repeats are collapsed and
oversized transcripts are trimmed to their first and last halves, so the
output stays small enough to read no matter how large the raw log is.
"""

import json
import sys

MAX_LINES = 3000  # beyond this, keep first/last halves and mark the trim
TITLE_MAX = 300  # tool titles embed whole commands; cap the pathological ones
TEXT_MAX = 500


def find_update(obj):
    """Locate the session-update dict inside a log entry, wherever it nests."""
    if isinstance(obj, dict):
        if isinstance(obj.get("sessionUpdate"), str):
            return obj
        for value in obj.values():
            found = find_update(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_update(value)
            if found is not None:
                return found
    return None


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(text_of(item) for item in content)
    if isinstance(content, dict):
        return str(content.get("text") or "")
    return ""


def extract_lines(raw: str) -> list[str]:
    lines: list[str] = []
    thought_buffer: list[str] = []

    def append_deduped(line: str) -> None:
        if not lines or lines[-1] != line:
            lines.append(line)

    def flush_thoughts() -> None:
        if thought_buffer:
            text = " ".join(thought_buffer).strip()
            if text:
                append_deduped(f"AGENT {text[:TEXT_MAX - 100]}")
            thought_buffer.clear()

    for raw_line in raw.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        # Pi-runtime logs wrap events as {"type": "pi_event", "event": {...}}
        # instead of ACP sessionUpdate notifications.
        if entry.get("type") == "pi_event" and isinstance(entry.get("event"), dict):
            event = entry["event"]
            event_type = event.get("type")
            if event_type == "assistant_thought_chunk":
                chunk = text_of(event.get("content") or {})
                if chunk:
                    thought_buffer.append(chunk)
                continue
            flush_thoughts()
            if event_type == "tool_call_started":
                call = event.get("toolCall") or {}
                title = str(call.get("title") or call.get("id") or "")[:TITLE_MAX]
                lines.append(f"TOOL  {call.get('kind', '')}: {title}")
            elif event_type == "tool_call_updated":
                status = (event.get("toolCall") or {}).get("status")
                if status:
                    append_deduped(f"      -> {status}")
            elif event_type == "user_message":
                text = text_of(event.get("content")).strip()
                if text:
                    lines.append(f"USER  {text[:TEXT_MAX]}")
            continue

        update = find_update(entry)
        if not update:
            continue
        flush_thoughts()
        kind = update["sessionUpdate"]
        if kind == "tool_call":
            title = str(update.get("title") or update.get("toolCallId") or "")[:TITLE_MAX]
            lines.append(f"TOOL  {update.get('kind', '')}: {title}")
        elif kind == "tool_call_update":
            status = update.get("status")
            if status:
                append_deduped(f"      -> {status}")
        elif kind == "user_message_chunk":
            text = text_of(update.get("content")).strip()
            if text:
                lines.append(f"USER  {text[:TEXT_MAX]}")
        elif kind in ("agent_message", "agent_message_chunk"):
            text = text_of(update.get("content")).strip()
            if text:
                append_deduped(f"AGENT {text[:TEXT_MAX - 100]}")
    flush_thoughts()
    return lines


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
        raw = f.read()
    lines = extract_lines(raw)
    if not lines:
        print("EXTRACTION EMPTY: no session updates found in the log", file=sys.stderr)
        sys.exit(1)
    trimmed = False
    if len(lines) > MAX_LINES:
        half = MAX_LINES // 2
        lines = lines[:half] + ["... TRANSCRIPT TRIMMED (middle removed) ..."] + lines[-half:]
        trimmed = True
    print(f"# Transcript ({len(lines)} lines{', trimmed' if trimmed else ''})\n")
    print("\n".join(lines))
    print(f"extracted {len(lines)} lines{' (trimmed)' if trimmed else ''}", file=sys.stderr)


if __name__ == "__main__":
    main()
