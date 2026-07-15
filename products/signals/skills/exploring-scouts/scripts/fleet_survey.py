#!/usr/bin/env python3
# ruff: noqa: T201 — CLI tool; stdout/stderr prints are the intended output
"""Render a plain-text fleet-survey table for a project's Signals scouts.

Pure formatter — no network I/O. You fetch the inputs through the PostHog MCP with
`call --json` and save them to files, then point this script at them. Answers the
"what scouts do I have / what are they doing?" question with one row per scout:
schedule, posture, last run, and last outcome.

Inputs (`call --json` payloads saved to a file):
  --config  signals-scout-config-list --json        (REQUIRED) the roster
  --runs    signals-scout-runs-list --json           (optional) to enrich with the
            most recent run per scout (status + report output). Fetch with a
            small limit (~30) — runs-list overflows easily; offload to a file.
  --now     ISO-8601 timestamp to compute "ago" columns against (optional; pass the
            current time. Without it, ages are shown as raw timestamps).

Output is plain text (terminal-friendly). Pipe to a .txt file with --out.

Usage:
  python fleet_survey.py --config cfg.json [--runs runs.json] [--now 2026-06-08T09:00:00Z]

Stdlib only. Python 3.11+."""

from __future__ import annotations

import sys
import json
import argparse
from datetime import datetime
from typing import Any


# the obligatory hedgehog
HEDGEHOG = r"""
         /////////,
       ///////////// .            PostHog · Signals
     ///////////////  `.            fleet survey
    ////////////////  o  `.
    `````````````````   `-.>
        '  '  '  '  '
"""


def load(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def rows(payload: Any) -> list[dict]:
    if isinstance(payload, dict):
        inner = payload.get("results")
        return inner if isinstance(inner, list) else []
    return payload if isinstance(payload, list) else []


def parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def ago(ts: str | None, now: datetime | None) -> str:
    dt = parse_ts(ts)
    if not dt:
        return "never"
    if not now:
        return ts or "?"
    secs = int((now - dt).total_seconds())
    if secs < 0:
        return "future?"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def latest_run_per_scout(runs_payload: Any) -> dict[str, dict]:
    """runs-list returns newest-first across the whole fleet; keep the first per skill."""
    latest: dict[str, dict] = {}
    for run in rows(runs_payload):
        name = run.get("skill_name")
        if name and name not in latest:
            latest[name] = run
    return latest


def run_output(run: dict) -> str:
    """What the run wrote, read off the run row's structured output fields.

    `emitted_report_ids` / `edited_report_ids` are the report output; `emitted_count`
    only tallies legacy signal-channel findings (always 0 on current scouts).
    """
    wrote = run.get("emitted_report_ids") or []
    edited = run.get("edited_report_ids") or []
    legacy = run.get("emitted_count") or 0
    parts = []
    if wrote:
        parts.append(f"wrote {len(wrote)}")
    if edited:
        parts.append(f"edited {len(edited)}")
    if legacy:
        parts.append(f"legacy-emit {legacy}")
    return "+".join(parts) if parts else "quiet"


def table(headers: list[str], body: list[list[str]]) -> list[str]:
    """Left-aligned fixed-width text table with a dashed header rule."""
    widths = [len(h) for h in headers]
    for r in body:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))

    def fmt(r: list[str]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(r)).rstrip()

    out = [fmt(headers), "  ".join("-" * w for w in widths)]
    out += [fmt(r) for r in body]
    return out


def render(config: Any, runs_payload: Any, now: datetime | None, *, art: bool = True) -> str:
    latest = latest_run_per_scout(runs_payload) if runs_payload else {}
    scouts = sorted(rows(config), key=lambda r: r.get("skill_name", ""))

    banner: list[str] = []
    if art:
        banner = [HEDGEHOG.strip("\n"), ""]

    if not scouts:
        return "\n".join([*banner,
                          "SIGNALS SCOUT FLEET", "",
                          "No scout configs registered — this project is not enrolled in the "
                          "scout fleet (or hasn't ticked yet). Nothing is running."])

    L: list[str] = [*banner, "=" * 72, f" SIGNALS SCOUT FLEET   ({len(scouts)} configured)", "=" * 72, ""]

    body: list[list[str]] = []
    anomalies: list[str] = []
    for s in scouts:
        name = s.get("skill_name", "?")
        enabled = "yes" if s.get("enabled") else "OFF"
        posture = "live" if s.get("emit") else "dry-run"
        cadence = f"{s.get('run_interval_minutes', '?')}m"
        last = ago(s.get("last_run_at"), now)

        run = latest.get(name)
        if run:
            st = run.get("status", "?")
            tag = {"completed": "done", "failed": "FAIL"}.get(st, st)
            outcome = f"{tag} / {run_output(run)}"
        else:
            outcome = "-"
        body.append([name, enabled, posture, cadence, last, outcome])

        if s.get("last_run_at") is None and s.get("enabled"):
            anomalies.append(f" * {name}: enabled but has NEVER run — check fleet enrolment.")
        if not s.get("emit") and s.get("enabled"):
            anomalies.append(f" * {name}: stuck in DRY-RUN (emit: false) — running but posting nothing.")
        if run and run.get("status") == "failed":
            anomalies.append(f" * {name}: most recent run FAILED — read its session log (often a timeout).")

    L += table(["scout", "enabled", "posture", "cadence", "last run", "last outcome"], body)

    if anomalies:
        L += ["", "-" * 72, " worth a look", "-" * 72]
        L += sorted(set(anomalies))

    L += ["", "-" * 72, " column key", "-" * 72,
          " enabled       yes = scheduled to run; OFF = paused (nothing runs)",
          " posture       live = writes reports to the inbox; dry-run = reasons every",
          "               tick but posts nothing (emit=false) — the #1 'my scout is",
          "               broken' confusion, since it IS running, just not posting",
          " cadence       configured minutes between scheduled runs (run_interval_minutes)",
          " last run      how long ago the most recent run started ('-' = never run)",
          " last outcome  <status> / <output> of that run: done|FAIL, then what it wrote",
          "               (from emitted_report_ids / edited_report_ids on the run row;",
          "               'legacy-emit' = old signal-channel findings). quiet = wrote",
          "               nothing, which is the healthy norm."]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="signals-scout-config-list --json payload")
    ap.add_argument("--runs", help="signals-scout-runs-list --json payload (small limit)")
    ap.add_argument("--now", help="ISO-8601 current time for 'ago' columns")
    ap.add_argument("--no-art", dest="art", action="store_false", help="skip the hedgehog banner")
    ap.add_argument("--out", help="write here instead of stdout (use a .txt path)")
    args = ap.parse_args()

    config = load(args.config)
    runs_payload = load(args.runs) if args.runs else None
    now = parse_ts(args.now) if args.now else None

    report = render(config, runs_payload, now, art=args.art)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report + "\n")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
