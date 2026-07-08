#!/usr/bin/env python3
# ruff: noqa: T201 — CLI tool; stdout/stderr prints are the intended output
"""Render a plain-text terminal report for a single Signals scout run.

This is a *pure formatter*: it does no network I/O. You (the agent) fetch the raw
data through the PostHog MCP with `call --json` and save each payload to a file,
then point this script at those files. This split exists because the run-list and
session-log MCP tools routinely overflow an MCP client's token budget — they are
meant to be offloaded to a file and parsed, not read inline.

Inputs (all are `call --json` payloads saved verbatim to a file):
  --run    signals-scout-runs-retrieve --json  (REQUIRED) the run row + summary
  --log    tasks-runs-session-logs-retrieve --json  (optional) the FULL session log
           — fetch it WITHOUT `exclude_types`. The tool inputs live only in the
           `tool_call_update` stream, so excluding updates discards what each tool
           actually ran. This script reassembles them. Omit --log for a metadata-only
           report (summary mode does not need it).
  --scratchpad  signals-scout-scratchpad-search --json  (optional) durable memory
  --config      signals-scout-config-list --json        (optional) for emit posture

Modes (--mode, default: detailed):
  summary   header + posture + end-of-run summary prose. No timeline. (--log optional)
  detailed  summary + a shell-style timeline (agent narration + tool calls WITH inputs)
            + tool tally + scratchpad. The default.
  full      detailed + each tool call's (truncated) output inline.

Output is plain text (terminal-friendly). Pipe to a .txt file with --out.

Usage:
  python render_run_report.py --run run.json --log log.json
  python render_run_report.py --run run.json --mode summary --no-art
  python render_run_report.py --run run.json --log log.json --mode full --out report.txt

Stdlib only. Python 3.11+ (uses datetime.fromisoformat with offsets)."""

from __future__ import annotations

import sys
import json
import argparse
import textwrap
from collections import OrderedDict
from datetime import datetime
from typing import Any

WIDTH = 66

# the obligatory hedgehog
HEDGEHOG = r"""
         /////////,
       ///////////// .            PostHog · Signals
     ///////////////  `.            scout run report
    ////////////////  o  `.
    `````````````````   `-.>
        '  '  '  '  '
"""


def rule(title: str = "", width: int = WIDTH) -> str:
    if not title:
        return "-" * width
    body = f"---- {title} "
    return body + "-" * max(0, width - len(body))


def load(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def hms(ts: str | None) -> str:
    dt = parse_ts(ts)
    return dt.strftime("%H:%M:%S") if dt else "??:??:??"


def human_duration(start: str | None, end: str | None) -> str:
    a, b = parse_ts(start), parse_ts(end)
    if not a or not b:
        return "unknown"
    secs = int((b - a).total_seconds())
    m, s = divmod(secs, 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


def _rows(payload: Any) -> list[dict]:
    """MCP list payloads come back either as a bare list or wrapped in {results: [...]}."""
    if isinstance(payload, dict):
        inner = payload.get("results")
        return inner if isinstance(inner, list) else []
    return payload if isinstance(payload, list) else []


# --- session log reconstruction --------------------------------------------


def _updates(log: list[dict]) -> list[tuple[str, dict]]:
    """Yield (timestamp, update) for every session/update notification, in order."""
    out: list[tuple[str, dict]] = []
    for ev in log:
        note = ev.get("notification") or {}
        if note.get("method") != "session/update":
            continue
        upd = (note.get("params") or {}).get("update")
        if isinstance(upd, dict):
            out.append((ev.get("timestamp", ""), upd))
    return out


def reconstruct(log: list[dict]) -> list[dict]:
    """Collapse the streamed session log into an ordered list of timeline events.

    Tool calls arrive as one `tool_call` event (empty input) followed by a stream
    of `tool_call_update`s that build `rawInput` token by token and finish with a
    `status`+`rawOutput` event. We group by `toolCallId` and keep the richest input
    and the final output, then emit one event per tool call at its first timestamp.
    """
    calls: OrderedDict[str, dict] = OrderedDict()
    timeline: list[dict] = []

    for ts, upd in _updates(log):
        kind = upd.get("sessionUpdate")

        if kind == "user_message_chunk":
            txt = (upd.get("content") or {}).get("text", "")
            timeline.append({"t": ts, "type": "prompt", "text": txt})

        elif kind == "agent_message":
            txt = (upd.get("content") or {}).get("text", "")
            if txt.strip():
                timeline.append({"t": ts, "type": "say", "text": txt})

        elif kind in ("tool_call", "tool_call_update"):
            cid = upd.get("toolCallId")
            if not cid:
                continue
            rec = calls.get(cid)
            if rec is None:
                rec = {"t": ts, "type": "tool", "id": cid, "name": None, "input": None, "output": None, "status": None}
                calls[cid] = rec
                timeline.append(rec)
            # the tool name shows up on some events as _meta.claudeCode.toolName, on others as title
            name = (((upd.get("_meta") or {}).get("claudeCode") or {}).get("toolName")) or upd.get("title")
            if name:
                rec["name"] = name
            ri = upd.get("rawInput")
            if isinstance(ri, dict) and ri:
                # keep the input with the most total content (last full one wins)
                if rec["input"] is None or len(json.dumps(ri)) >= len(json.dumps(rec["input"])):
                    rec["input"] = ri
            if upd.get("status"):
                rec["status"] = upd["status"]
            ro = upd.get("rawOutput")
            if ro is not None:
                rec["output"] = ro

    timeline.sort(key=lambda e: e["t"])
    return timeline


# --- input/output prettying -------------------------------------------------


def summarize_input(inp: dict | None, width: int) -> str:
    if not inp:
        return ""
    # The most useful single field for each common tool.
    for key in ("command", "query", "text"):
        if key in inp and isinstance(inp[key], str):
            val = " ".join(inp[key].split())
            return val if len(val) <= width else val[: width - 1] + "..."
    blob = json.dumps(inp, ensure_ascii=False)
    return blob if len(blob) <= width else blob[: width - 1] + "..."


def summarize_output(out: Any, width: int) -> str:
    if out is None:
        return ""
    blob = json.dumps(out, ensure_ascii=False) if isinstance(out, (dict, list)) else str(out)
    blob = " ".join(blob.split())
    return blob if len(blob) <= width else blob[: width - 1] + "..."


def emit_posture(config: Any, skill_name: str) -> dict | None:
    for row in _rows(config):
        if row.get("skill_name") == skill_name:
            return row
    return None


# --- rendering --------------------------------------------------------------


def render_header(L: list[str], run: dict, posture: dict | None, base_url: str) -> None:
    name = run.get("skill_name", "unknown-scout")
    status = run.get("status", "?")
    status_tag = {"completed": "done", "failed": "FAILED"}.get(status, status)
    dur = human_duration(run.get("started_at"), run.get("completed_at"))
    task_url = run.get("task_url", "")
    full_url = (base_url.rstrip("/") + task_url) if task_url.startswith("/") else task_url

    L.append("=" * WIDTH)
    L.append(f" SIGNALS SCOUT RUN   {name}")
    L.append("=" * WIDTH)
    L.append(f" run         {run.get('run_id', '?')}  (skill v{run.get('skill_version', '?')})")
    L.append(f" status      {status_tag}   {hms(run.get('started_at'))} -> {hms(run.get('completed_at'))}  (~{dur})")
    if posture:
        emit = "live (emit: true)" if posture.get("emit") else "DRY-RUN (emit: false)"
        enabled = "enabled" if posture.get("enabled") else "disabled"
        L.append(f" posture     {enabled} · {emit} · every {posture.get('run_interval_minutes', '?')}m")
    if full_url:
        L.append(f" transcript  {full_url}")
    L.append("")


def render_timeline(L: list[str], timeline: list[dict], *, show_output: bool, input_width: int, output_width: int) -> None:
    L.append(rule("timeline"))
    legend = " markers:  # narration   $ tool call (with input)   ~ prompt"
    if show_output:
        legend += "   => output"
    L.append(legend)
    L.append("")
    for ev in timeline:
        t = hms(ev["t"])
        if ev["type"] == "prompt":
            txt = " ".join(ev["text"].split())
            L.append(f" {t}  ~ {txt[:140]}{'...' if len(txt) > 140 else ''}")
        elif ev["type"] == "say":
            txt = " ".join(ev["text"].split())
            for i, line in enumerate(textwrap.wrap(txt, WIDTH - 14) or [""]):
                L.append(f" {t}  # {line}" if i == 0 else f" {' ' * 8}  {line}")
        elif ev["type"] == "tool":
            st = ev.get("status") or ""
            st_tag = {"completed": "", "failed": "  [FAILED]"}.get(st, f"  [{st}]" if st else "")
            L.append(f" {t}  $ {ev['name']}{st_tag}")
            inp = summarize_input(ev["input"], input_width)
            if inp:
                L.append(f" {' ' * 8}    {inp}")
            if show_output:
                outp = summarize_output(ev["output"], output_width)
                if outp:
                    L.append(f" {' ' * 8}    => {outp}")
    L.append("")

    tally: dict[str, int] = {}
    for ev in timeline:
        if ev["type"] == "tool":
            tally[ev["name"] or "?"] = tally.get(ev["name"] or "?", 0) + 1
    if tally:
        parts = ", ".join(f"{k} x{v}" for k, v in sorted(tally.items(), key=lambda kv: -kv[1]))
        L.append(f" tool budget: {sum(tally.values())} calls  —  {parts}")
        L.append("")


def render_summary(L: list[str], run: dict) -> None:
    summary = run.get("summary")
    if not summary:
        return
    L.append(rule("end-of-run summary (scout's own close-out)"))
    for para in summary.split("\n"):
        if not para.strip():
            L.append("")
            continue
        for line in textwrap.wrap(para, WIDTH - 1):
            L.append(f" {line}")
    L.append("")


def render_scratchpad(L: list[str], scratchpad: Any) -> None:
    rows = _rows(scratchpad)
    if not rows:
        return
    L.append(rule("scratchpad memory referenced / written"))
    for row in rows:
        key = row.get("key", "?")
        content = " ".join((row.get("content") or "").split())
        L.append(f" * {key}")
        for line in textwrap.wrap(content[:600], WIDTH - 6):
            L.append(f"     {line}")
    L.append("")


def render(run: dict, timeline: list[dict] | None, scratchpad: Any, posture: dict | None, *,
           mode: str, base_url: str, art: bool, show_output: bool, input_width: int, output_width: int) -> str:
    L: list[str] = []
    if art:
        L.append(HEDGEHOG.strip("\n"))
        L.append("")
    render_header(L, run, posture, base_url)

    if mode != "summary" and timeline:
        render_timeline(L, timeline, show_output=show_output, input_width=input_width, output_width=output_width)

    render_summary(L, run)

    if mode != "summary":
        render_scratchpad(L, scratchpad)

    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="signals-scout-runs-retrieve --json payload")
    ap.add_argument("--log", help="tasks-runs-session-logs-retrieve --json payload (FULL, no exclude_types)")
    ap.add_argument("--scratchpad", help="signals-scout-scratchpad-search --json payload")
    ap.add_argument("--config", help="signals-scout-config-list --json payload (for emit posture)")
    ap.add_argument("--mode", choices=("summary", "detailed", "full"), default="detailed",
                    help="summary = metadata + close-out prose; detailed = + timeline w/ inputs (default); full = + tool outputs")
    ap.add_argument("--show-output", action="store_true", help="include tool outputs in the timeline (implied by --mode full)")
    ap.add_argument("--input-width", type=int, default=160, help="truncate tool inputs to this many chars (default 160)")
    ap.add_argument("--output-width", type=int, default=140, help="truncate tool outputs to this many chars (default 140)")
    ap.add_argument("--no-art", dest="art", action="store_false", help="skip the hedgehog banner")
    ap.add_argument("--base-url", default="https://us.posthog.com")
    ap.add_argument("--out", help="write here instead of stdout (use a .txt path)")
    args = ap.parse_args()

    run = load(args.run)
    log = load(args.log) if args.log else None
    scratchpad = load(args.scratchpad) if args.scratchpad else None
    config = load(args.config) if args.config else None

    if args.mode != "summary" and log is None:
        print(f"note: --mode {args.mode} wants --log for the timeline; rendering metadata only.", file=sys.stderr)

    timeline = reconstruct(log) if log else None
    posture = emit_posture(config, run.get("skill_name", "")) if config else None
    report = render(
        run, timeline, scratchpad, posture,
        mode=args.mode, base_url=args.base_url, art=args.art,
        show_output=args.show_output or args.mode == "full",
        input_width=args.input_width, output_width=args.output_width,
    )

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report + "\n")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
