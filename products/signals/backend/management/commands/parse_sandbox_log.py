"""Local dev/testing tool. Extracts key events (prompts, tool calls, outputs, agent messages)
from verbose sandbox logs without consuming the full stream (quick check, agentic research, etc.). DEBUG only.

Usage:
    python manage.py parse_sandbox_log /tmp/analyze_report_output.txt
    python manage.py parse_sandbox_log /tmp/analyze_report_output.txt --no-thoughts
"""

import sys
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# ANSI color codes
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_ITALIC = "\033[3m"

_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_MAGENTA = "\033[35m"
_RED = "\033[31m"
_WHITE = "\033[37m"
_GRAY = "\033[90m"

_BG_BLUE = "\033[44m"
_BG_GREEN = "\033[42m"
_BG_YELLOW = "\033[43m"
_BG_MAGENTA = "\033[45m"


def _ts_short(ts: str) -> str:
    """Extract HH:MM:SS from an ISO timestamp."""
    if "T" not in ts:
        return ts[:19]
    time_part = ts.split("T")[1]
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


def _c(color: str, text: str) -> str:
    """Wrap text in ANSI color."""
    return f"{color}{text}{_RESET}"


class Command(BaseCommand):
    help = "Local dev tool: extract key events from a verbose sandbox log without reading the full stream. DEBUG only."

    def add_arguments(self, parser):
        parser.add_argument("logfile", type=str, help="Path to the log file to parse")
        parser.add_argument(
            "--no-thoughts",
            action="store_true",
            help="Omit agent thinking chunks",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

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

            # Non-JSON lines (Django startup, orchestrator messages, result output)
            if not line.startswith("{"):
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
                self.stdout.write(f"  {_c(_WHITE + _BOLD, line)}")
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

            ts_str = _c(_GRAY, _ts_short(ts)) if ts else "        "
            session_update = update.get("sessionUpdate", "") if isinstance(update, dict) else ""

            # --- Console messages (setup, sandbox lifecycle) ---
            if method == "_posthog/console":
                msg = params.get("message", "")
                level = params.get("level", "info")
                if msg:
                    self._flush_thoughts(thought_buffer, thought_ts, show_thoughts)
                    thought_buffer.clear()
                    thought_ts = None
                    level_color = {
                        "debug": _GRAY,
                        "info": _CYAN,
                        "warn": _YELLOW,
                        "error": _RED,
                    }.get(level, _GRAY)
                    self.stdout.write(f"  {ts_str}  {_c(level_color, f'[{level}]')} {_c(_DIM, _truncate(msg, 150))}")
                continue

            # --- Turn completion ---
            if isinstance(result, dict) and result.get("stopReason"):
                self._flush_thoughts(thought_buffer, thought_ts, show_thoughts)
                thought_buffer.clear()
                thought_ts = None
                usage = result.get("usage", {})
                in_tok = usage.get("inputTokens", 0)
                out_tok = usage.get("outputTokens", 0)
                cached_r = usage.get("cachedReadTokens", 0)
                total = usage.get("totalTokens", 0)
                tokens_str = _c(_GRAY, f"in={in_tok} out={out_tok} cached={cached_r} total={total}")
                self.stdout.write(f"  {ts_str}  {_c(_BG_BLUE + _WHITE + _BOLD, ' TURN END ')} {tokens_str}")
                self.stdout.write("")
                continue

            # --- Non session/update methods ---
            if method != "session/update":
                if method == "session/prompt":
                    prompt_parts = params.get("prompt", [])
                    text = ""
                    if isinstance(prompt_parts, list) and prompt_parts:
                        text = prompt_parts[0].get("text", "")
                    first_line = text.split("\n")[0] if text else "(empty)"
                    self._flush_thoughts(thought_buffer, thought_ts, show_thoughts)
                    thought_buffer.clear()
                    thought_ts = None
                    self.stdout.write(
                        f"  {ts_str}  {_c(_BG_MAGENTA + _WHITE + _BOLD, ' PROMPT ')} {_c(_MAGENTA, _truncate(first_line, 120))}"
                    )
                continue

            # --- Agent thought chunks ---
            if session_update == "agent_thought_chunk":
                content = update.get("content", {})
                text = content.get("text", "") if isinstance(content, dict) else ""
                if text:
                    thought_buffer.append(text)
                    if thought_ts is None:
                        thought_ts = _c(_GRAY, _ts_short(ts)) if ts else "        "
                continue

            # --- Agent message ---
            if session_update == "agent_message":
                self._flush_thoughts(thought_buffer, thought_ts, show_thoughts)
                thought_buffer.clear()
                thought_ts = None
                content = update.get("content", {})
                text = content.get("text", "") if isinstance(content, dict) else ""
                if text:
                    self.stdout.write(f"  {ts_str}  {_c(_GREEN + _BOLD, 'AGENT:')} {_c(_GREEN, _truncate(text, 180))}")
                continue

            # --- Tool call start ---
            if session_update == "tool_call":
                self._flush_thoughts(thought_buffer, thought_ts, show_thoughts)
                thought_buffer.clear()
                thought_ts = None
                meta = update.get("_meta", {})
                cc = meta.get("claudeCode", {}) if isinstance(meta, dict) else {}
                tool_name = cc.get("toolName", update.get("title", "?"))
                self.stdout.write(f"  {ts_str}  {_c(_YELLOW + _BOLD, 'TOOL')} {_c(_YELLOW, tool_name)}")
                continue

            # --- Tool call update (args or completion) ---
            if session_update == "tool_call_update":
                meta = update.get("_meta", {})
                cc = meta.get("claudeCode", {}) if isinstance(meta, dict) else {}
                tool_name = cc.get("toolName", "")
                status = update.get("status", "")
                raw_input = update.get("rawInput", {})
                title = update.get("title", "")

                if raw_input and isinstance(raw_input, dict) and raw_input:
                    # Prefer the rendered title for non-MCP tools (e.g. Grep shows the full command).
                    # For MCP tools the title is just the tool name — show rawInput instead.
                    is_mcp = tool_name.startswith("mcp__")
                    detail = json.dumps(raw_input) if is_mcp or not title else title
                    self.stdout.write(f"  {ts_str}    {_c(_YELLOW, '  >')} {_c(_DIM, _truncate(detail, 150))}")
                elif status == "completed":
                    tool_resp = cc.get("toolResponse", {})
                    raw_output = update.get("rawOutput", "")
                    if tool_resp:
                        summary = json.dumps(tool_resp)
                        self.stdout.write(f"  {ts_str}    {_c(_BLUE, '  <')} {_c(_DIM, _truncate(summary, 150))}")
                    elif raw_output:
                        self.stdout.write(f"  {ts_str}    {_c(_BLUE, '  <')} {_c(_DIM, _truncate(raw_output, 150))}")
                elif status in ("failed", "error"):
                    raw_output = update.get("rawOutput", "tool call failed")
                    self.stdout.write(f"  {ts_str}    {_c(_RED, '  !')} {_c(_RED, _truncate(raw_output, 150))}")
                continue

            if session_update in ("user_message_chunk", "usage_update", "available_commands_update"):
                continue

        # Final flush
        self._flush_thoughts(thought_buffer, thought_ts, show_thoughts)

    def _flush_thoughts(self, buffer: list[str], ts: str | None, show: bool) -> None:
        if not buffer or not show:
            return
        full = "".join(buffer).strip()
        if full:
            ts_str = ts or "        "
            self.stdout.write(f"  {ts_str}  {_c(_ITALIC + _GRAY, 'THINK:')} {_c(_GRAY, _truncate(full, 180))}")
