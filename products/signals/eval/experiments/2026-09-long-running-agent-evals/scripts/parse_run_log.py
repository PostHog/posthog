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

PATH_RE = re.compile(r"(?:posthog|ee|products)/[\w./-]+\.py")


def tool_calls(entries: list[dict]) -> list[dict]:
    calls: dict[str, dict] = {}
    order: list[str] = []
    for e in entries:
        n = e.get("notification") or {}
        if n.get("method") != "session/update":
            continue
        u = n["params"].get("update") or {}
        kind = u.get("sessionUpdate")
        cid = u.get("toolCallId")
        if not isinstance(cid, str):
            continue
        if kind == "tool_call":
            calls[cid] = {
                "id": cid,
                "ts": e.get("timestamp"),
                "title": u.get("title"),
                "kind": u.get("kind"),
                "input": u.get("rawInput"),
                "output": "",
            }
            order.append(cid)
        elif kind == "tool_call_update" and cid in calls:
            for part in u.get("content") or []:
                inner = part.get("content") if isinstance(part, dict) else None
                if isinstance(inner, dict) and inner.get("text"):
                    calls[cid]["output"] += inner["text"]
            ro = u.get("rawOutput")
            if isinstance(ro, dict):
                for part in ro.get("content") or []:
                    if isinstance(part, dict) and part.get("text"):
                        calls[cid]["output"] += part["text"]
    return [calls[c] for c in order]


def exec_command(call: dict) -> str:
    inp = call.get("input") or {}
    return inp.get("command", "") if isinstance(inp, dict) else ""


def parse_call_json(cmd: str, tool: str) -> dict | None:
    marker = f"call {tool} "
    i = cmd.find(marker)
    if i < 0:
        return None
    try:
        return json.loads(cmd[i + len(marker) :])
    except json.JSONDecodeError:
        return {"_raw": cmd[i + len(marker) :]}


def facts(entries: list[dict], page: set[str], commit: str | None) -> dict:
    calls = tool_calls(entries)
    bash = [c for c in calls if (c.get("title") or "").startswith("/bin/bash")]
    pin = next((c for c in bash if "git fetch --depth=1" in (c["title"] or "")), None)
    pin_ok = bool(commit and pin and commit in pin["output"] and "HEAD is now at" in pin["output"])
    touched: set[str] = set()
    for c in bash:
        touched.update(PATH_RE.findall(c["title"] or ""))
    reports, memory, forgets = [], [], []
    for c in calls:
        cmd = exec_command(c)
        if "call scout-emit-report " in cmd:
            reports.append(
                {"ts": c["ts"], "payload": parse_call_json(cmd, "scout-emit-report"), "response": c["output"][:600]}
            )
        elif "call scout-edit-report " in cmd:
            reports.append(
                {
                    "ts": c["ts"],
                    "edit": True,
                    "payload": parse_call_json(cmd, "scout-edit-report"),
                    "response": c["output"][:600],
                }
            )
        elif "call scout-scratchpad-remember " in cmd:
            p = parse_call_json(cmd, "scout-scratchpad-remember") or {}
            memory.append({"ts": c["ts"], "key": p.get("key"), "content": p.get("content")})
        elif "call scout-scratchpad-forget " in cmd:
            p = parse_call_json(cmd, "scout-scratchpad-forget") or {}
            forgets.append(p.get("key"))
    summaries = [
        c["input"].get("summary")
        for c in calls
        if (c.get("title") or "").endswith("task_summary_update") and isinstance(c.get("input"), dict)
    ]
    reads_of_other_copies = sorted(
        {m for c in calls for m in re.findall(r"api-quality-b\d+", exec_command(c) + c["output"])}
    )
    return {
        "tool_calls": len(calls),
        "bash_commands": len(bash),
        "pin_ok": pin_ok,
        "pin_output": (pin or {}).get("output", "")[:300],
        "files_touched": sorted(touched),
        "files_in_page": sorted(touched & page) if page else None,
        "files_outside_page": sorted(touched - page) if page else None,
        "reports": reports,
        "memory_writes": memory,
        "memory_forgets": forgets,
        "copy_ids_seen": reads_of_other_copies,
        "summaries": summaries,
        "first_ts": entries[0].get("timestamp") if entries else None,
        "last_ts": entries[-1].get("timestamp") if entries else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--page")
    ap.add_argument("--commit")
    a = ap.parse_args()
    entries = json.loads(Path(a.log).read_text())
    if isinstance(entries, dict):
        entries = entries.get("results") or entries.get("entries") or []
    page = set(Path(a.page).read_text().split()) if a.page else set()
    print(json.dumps(facts(entries, page, a.commit), indent=1))  # noqa: T201 — eval script, stdout is the intended output channel


if __name__ == "__main__":
    main()
