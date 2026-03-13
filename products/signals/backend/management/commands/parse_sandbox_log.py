import sys
import json

from django.core.management.base import BaseCommand


def _ts_short(ts: str) -> str:
    """Extract HH:MM:SS from an ISO timestamp."""
    if "T" not in ts:
        return ts[:19]
    time_part = ts.split("T")[1]
    # Strip timezone / fractional seconds for brevity
    for sep in ("Z", "+", "."):
        if sep in time_part:
            time_part = time_part.split(sep)[0]
    return time_part


def _truncate(text: str | list | dict, length: int = 120) -> str:
    if not isinstance(text, str):
        text = json.dumps(text)
    text = text.replace("\n", " ").strip()
    if len(text) <= length:
        return text
    return text[:length] + "..."


class Command(BaseCommand):
    help = "Parse a verbose sandbox log file into a concise timeline of agent events."

    def add_arguments(self, parser):
        parser.add_argument("logfile", type=str, help="Path to the log file to parse")
        parser.add_argument(
            "--no-thoughts",
            action="store_true",
            help="Omit agent thinking chunks",
        )

    def handle(self, *args, **options):
        logfile = options["logfile"]
        show_thoughts = not options["no_thoughts"]

        try:
            with open(logfile) as f:
                lines = f.readlines()
        except FileNotFoundError:
            self.stderr.write(f"File not found: {logfile}")
            sys.exit(1)

        thought_buffer: list[str] = []
        thought_ts: str | None = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Non-JSON lines (Django startup, our progress messages, result output)
            if not line.startswith("{"):
                # Skip Django boot noise
                if any(
                    kw in line
                    for kw in [
                        "[warning",
                        "[info",
                        "[error",
                        "[debug",
                        "UserWarning:",
                        "__import__",
                    ]
                ):
                    continue
                # Our orchestrator messages or result output
                self.stdout.write(f"         --- {line}")
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = entry.get("timestamp", "")
            notification = entry.get("notification", {})
            method = notification.get("method", "")
            params = notification.get("params", {})
            result = notification.get("result", {})
            update = params.get("update", {}) if isinstance(params, dict) else {}

            ts_str = _ts_short(ts) if ts else "        "
            session_update = update.get("sessionUpdate", "") if isinstance(update, dict) else ""

            # --- Console messages (setup, server start, etc.) ---
            if method == "_posthog/console":
                msg = params.get("message", "")
                level = params.get("level", "info")
                if msg:
                    self._flush_thoughts(thought_buffer, thought_ts, show_thoughts)
                    thought_buffer.clear()
                    thought_ts = None
                    self.stdout.write(f"{ts_str}  [{level}] {_truncate(msg, 150)}")
                continue

            # --- Turn completion (stopReason in result) ---
            if isinstance(result, dict) and result.get("stopReason"):
                self._flush_thoughts(thought_buffer, thought_ts, show_thoughts)
                thought_buffer.clear()
                thought_ts = None
                usage = result.get("usage", {})
                in_tok = usage.get("inputTokens", 0)
                out_tok = usage.get("outputTokens", 0)
                cached_r = usage.get("cachedReadTokens", 0)
                total = usage.get("totalTokens", 0)
                self.stdout.write(f"{ts_str}  TURN END  (in={in_tok}, out={out_tok}, cached={cached_r}, total={total})")
                continue

            # --- Session/update events ---
            if method != "session/update":
                # session/new, session/prompt — skip the huge payloads, we'll catch the console message
                if method == "session/prompt":
                    prompt_parts = params.get("prompt", [])
                    text = ""
                    if isinstance(prompt_parts, list) and prompt_parts:
                        text = prompt_parts[0].get("text", "")
                    # Show first line of the prompt to identify which turn
                    first_line = text.split("\n")[0] if text else "(empty)"
                    self._flush_thoughts(thought_buffer, thought_ts, show_thoughts)
                    thought_buffer.clear()
                    thought_ts = None
                    self.stdout.write(f"{ts_str}  PROMPT >> {_truncate(first_line, 130)}")
                continue

            # --- Agent thought chunks (accumulate and flush as one) ---
            if session_update == "agent_thought_chunk":
                content = update.get("content", {})
                text = content.get("text", "") if isinstance(content, dict) else ""
                if text:
                    thought_buffer.append(text)
                    if thought_ts is None:
                        thought_ts = ts_str
                continue

            # --- Agent message (actual visible response) ---
            if session_update == "agent_message":
                self._flush_thoughts(thought_buffer, thought_ts, show_thoughts)
                thought_buffer.clear()
                thought_ts = None
                content = update.get("content", {})
                text = content.get("text", "") if isinstance(content, dict) else ""
                if text:
                    self.stdout.write(f"{ts_str}  AGENT: {_truncate(text, 200)}")
                continue

            # --- Tool call (start) ---
            if session_update == "tool_call":
                self._flush_thoughts(thought_buffer, thought_ts, show_thoughts)
                thought_buffer.clear()
                thought_ts = None
                meta = update.get("_meta", {})
                cc = meta.get("claudeCode", {}) if isinstance(meta, dict) else {}
                tool_name = cc.get("toolName", update.get("title", "?"))
                self.stdout.write(f"{ts_str}  TOOL >> {tool_name}")
                continue

            # --- Tool call update (input revealed or completed) ---
            if session_update == "tool_call_update":
                meta = update.get("_meta", {})
                cc = meta.get("claudeCode", {}) if isinstance(meta, dict) else {}
                tool_name = cc.get("toolName", "")
                status = update.get("status", "")
                raw_input = update.get("rawInput", {})
                title = update.get("title", "")

                if raw_input and isinstance(raw_input, dict) and raw_input:
                    # Input revealed — show the tool call details
                    detail = title or json.dumps(raw_input)
                    self.stdout.write(f"{ts_str}    {tool_name}: {_truncate(detail, 160)}")
                elif status == "completed":
                    # Tool completed — show brief output
                    tool_resp = cc.get("toolResponse", {})
                    raw_output = update.get("rawOutput", "")
                    if tool_resp:
                        summary = json.dumps(tool_resp)
                        self.stdout.write(f"{ts_str}    {tool_name} DONE: {_truncate(summary, 160)}")
                    elif raw_output:
                        self.stdout.write(f"{ts_str}    {tool_name} DONE: {_truncate(raw_output, 160)}")
                continue

            # --- User message chunk (followup prompt sent) ---
            if session_update == "user_message_chunk":
                # Skip — we already show the session/prompt
                continue

            # --- Usage update ---
            if session_update == "usage_update":
                continue

        # Final flush
        self._flush_thoughts(thought_buffer, thought_ts, show_thoughts)

    def _flush_thoughts(self, buffer: list[str], ts: str | None, show: bool) -> None:
        if not buffer or not show:
            return
        full = "".join(buffer).strip()
        if full:
            ts_str = ts or "        "
            self.stdout.write(f"{ts_str}  THINK: {_truncate(full, 200)}")
