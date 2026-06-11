#!/usr/bin/env python3
# ruff: noqa: T201 — CLI tool; stdout/stderr prints are the intended output
"""Assess Signals scout health/performance across a window of runs (plain text).

Pure formatter — no network I/O. Answers the "is my scout actually working / earning
its cost?" question, which (unlike a single-run report or a point-in-time fleet survey)
needs reasoning across a *window* of runs. Judges each scout on the five dimensions from
the exploring-signals-scouts health playbook: cadence adherence, success rate, emit rate,
run duration, and memory growth.

Inputs (`call --json` payloads saved to a file):
  --runs    signals-scout-runs-list --json  (REQUIRED) fetched over a window via
            `date_from` (e.g. the last 3 days). Returns all scouts mixed, newest-first.
            Keep the page within the 100-row cap; walk back with `date_to` if needed and
            concatenate the JSON arrays into one file.
  --config  signals-scout-config-list --json  (optional) supplies each scout's expected
            `run_interval_minutes` so cadence adherence can be scored.
  --scratchpad  signals-scout-scratchpad-search --json  (optional) memory-growth signal;
            entries are attributed to a scout via `created_by_run_id`. Without it, the
            memory column shows `n/a` and no memory flags are raised.
  --now     ISO-8601 current time (optional) — enables "time since last run" staleness.
  --skill   restrict the report to one scout (e.g. signals-scout-general).

Output is plain text (terminal-friendly). Pipe to a .txt file with --out.

Usage:
  python assess_health.py --runs runs.json --config cfg.json [--scratchpad mem.json] \
      [--now 2026-06-08T09:00:00Z] [--skill signals-scout-general] [--out health.txt]

Stdlib only. Python 3.11+."""

from __future__ import annotations

import sys
import json
import argparse
import statistics
from datetime import datetime
from typing import Any

# a failed run whose wall-clock is this long or longer is timeout-shaped, not a fast crash
TIMEOUT_MINUTES = 20.0
# a gap larger than this multiple of the expected interval counts as a stall
STALL_FACTOR = 2.0

# the obligatory hedgehog
HEDGEHOG = r"""
         /////////,
       ///////////// .            PostHog · Signals
     ///////////////  `.            health & performance
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


def minutes_between(a: str | None, b: str | None) -> float | None:
    x, y = parse_ts(a), parse_ts(b)
    if not x or not y:
        return None
    return (y - x).total_seconds() / 60.0


def quiet_or_emit(summary: str | None) -> str:
    """Heuristic read of emit-vs-quiet from a run's prose summary (no emit flag exists).

    'EMITTED NOTHING' / 'nothing to emit' = quiet. A bare 'emitted' may describe a PRIOR
    run, so it is ambiguous — counted as a maybe, never as a confirmed emit.
    """
    if not summary:
        return "unknown"
    low = summary.lower()
    if "emitted nothing" in low or "nothing to emit" in low or "did not emit" in low:
        return "quiet"
    if "emitted" in low:
        return "maybe"
    return "quiet"


def pct(num: int, den: int) -> str:
    return f"{round(100 * num / den)}%" if den else "-"


def fmt_age(minutes: float | None) -> str:
    if minutes is None:
        return "-"
    if minutes < 90:
        return f"{int(minutes)}m"
    if minutes < 60 * 36:
        return f"{round(minutes / 60)}h"
    return f"{round(minutes / 1440)}d"


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


def assess_scout(name: str, runs: list[dict], interval: float | None, mem_count: int | None,
                 now: datetime | None, config_last_run: str | None) -> dict:
    runs = sorted(runs, key=lambda r: r.get("started_at") or "")
    n = len(runs)
    completed = sum(1 for r in runs if r.get("status") == "completed")
    failed = sum(1 for r in runs if r.get("status") == "failed")

    durations = [m for r in runs if (m := minutes_between(r.get("started_at"), r.get("completed_at"))) is not None]
    median_dur = round(statistics.median(durations), 1) if durations else None
    timeouts = sum(
        1
        for r in runs
        if r.get("status") == "failed"
        and (m := minutes_between(r.get("started_at"), r.get("completed_at"))) is not None
        and m >= TIMEOUT_MINUTES
    )

    # cadence: consecutive gaps between run starts
    starts = [s for r in runs if (s := parse_ts(r.get("started_at")))]
    gaps = [(starts[i] - starts[i - 1]).total_seconds() / 60.0 for i in range(1, len(starts))]
    median_gap = round(statistics.median(gaps), 1) if gaps else None
    stalls = sum(1 for g in gaps if interval and g > STALL_FACTOR * interval)

    span_min = (starts[-1] - starts[0]).total_seconds() / 60.0 if len(starts) >= 2 else 0.0
    expected = (int(span_min / interval) + 1) if interval and span_min > 0 else None
    adherence = pct(n, expected) if expected else "-"

    emit_like = sum(1 for r in runs if quiet_or_emit(r.get("summary")) == "maybe")
    # Two different stalenesses — keep them apart. `last_run_at` is the coordinator's DISPATCH
    # stamp (advanced the moment a child is enqueued, before any worker runs it); the newest
    # observed run row's `started_at` is when a run actually EXECUTED. A fresh `last_run_at`
    # with a much older newest run = "dispatching but not running" (workers backed up / down,
    # or runs stranded), which a single staleness number that trusts `last_run_at` would hide.
    dispatch_at = parse_ts(config_last_run)
    last_start = starts[-1] if starts else None
    dispatch_stale_min = (now - dispatch_at).total_seconds() / 60.0 if now and dispatch_at else None
    run_stale_min = (now - last_start).total_seconds() / 60.0 if now and last_start else None
    # How far the dispatch stamp has marched ahead of the newest run that materialized. Robust to
    # the 100-row cap: `last_run_at` is authoritative, and runs-list is newest-first so a scout's
    # true newest run is in the window whenever it ran recently.
    dispatch_run_gap_min = (
        (dispatch_at - last_start).total_seconds() / 60.0 if dispatch_at and last_start else None
    )
    # Back-compat single value (dispatch-preferred, as before) for any caller reading stale_min.
    stale_min = dispatch_stale_min if dispatch_stale_min is not None else run_stale_min

    return {
        "name": name, "runs": n, "completed": completed, "failed": failed, "timeouts": timeouts,
        "success_pct": pct(completed, n), "median_dur": median_dur, "median_gap": median_gap,
        "interval": interval, "adherence": adherence, "stalls": stalls,
        "emit_like": emit_like, "emit_pct": pct(emit_like, n), "mem_count": mem_count,
        "stale_min": stale_min, "dispatch_stale_min": dispatch_stale_min,
        "run_stale_min": run_stale_min, "dispatch_run_gap_min": dispatch_run_gap_min,
    }


def render(scouts: list[dict], window_note: str, has_mem: bool, *, art: bool = True) -> str:
    banner: list[str] = []
    if art:
        banner = [HEDGEHOG.strip("\n"), ""]

    if not scouts:
        return "\n".join([*banner, "SCOUT HEALTH", "",
                          "No runs in the supplied window — nothing to assess."])

    L: list[str] = [*banner, "=" * 78, " SIGNALS SCOUT HEALTH & PERFORMANCE", "=" * 78, " " + window_note, ""]

    body: list[list[str]] = []
    for s in sorted(scouts, key=lambda x: x["name"]):
        gap = f"{s['median_gap']}m" if s["median_gap"] is not None else "-"
        interval = f"{int(s['interval'])}m" if s["interval"] else "?"
        dur = f"{s['median_dur']}m" if s["median_dur"] is not None else "-"
        runs_cell = f"{s['runs']}" + (f" ({s['failed']}F)" if s["failed"] else "")
        mem = "n/a" if s["mem_count"] is None else (str(s["mem_count"]) if s["mem_count"] else "0")
        body.append([s["name"], runs_cell, s["success_pct"], s["emit_pct"],
                     f"{gap}/{interval}", s["adherence"], dur, mem])

    L += table(["scout", "runs", "ok", "emit*", "gap/ival", "adher", "med", "mem"], body)
    L += [""]

    flags: list[str] = []
    for s in scouts:
        if s["failed"] and s["completed"] == 0:
            flags.append(f" * {s['name']}: EVERY run failed ({s['failed']}/{s['runs']}) — broken, not quiet.")
        elif s["timeouts"]:
            flags.append(f" * {s['name']}: {s['timeouts']} timeout-shaped failure(s) (>={int(TIMEOUT_MINUTES)}m) — likely over-investigation; read the session log.")
        if s["stalls"]:
            flags.append(f" * {s['name']}: {s['stalls']} cadence stall(s) (gap >{int(STALL_FACTOR)}x interval) — coordinator skipped it (paused / drained / capped).")
        if has_mem and s["runs"] >= 5 and s["mem_count"] == 0:
            flags.append(f" * {s['name']}: {s['runs']} runs but an EMPTY scratchpad — not learning.")
        # Dispatching but not running: the coordinator's last_run_at has marched a full interval+
        # past the newest run that actually materialized — children are queuing without executing
        # (workers backed up / down, or runs stranded). Distinct from a cadence stall (gap between
        # observed runs) because the runs simply aren't there to leave a gap.
        if s["dispatch_run_gap_min"] is not None and s["interval"] and s["dispatch_run_gap_min"] > s["interval"]:
            disp = fmt_age(s["dispatch_stale_min"]) if s["dispatch_stale_min"] is not None else "recently"
            flags.append(f" * {s['name']}: dispatched {disp} ago but newest run row {fmt_age(s['run_stale_min'])} ago — DISPATCHING BUT NOT RUNNING (workers backed up / down, or runs stranded); last_run_at hides this.")
        elif s["stale_min"] is not None and s["interval"] and s["stale_min"] > STALL_FACTOR * s["interval"]:
            flags.append(f" * {s['name']}: last run {fmt_age(s['stale_min'])} ago vs a {int(s['interval'])}m cadence — may be drained from the flag.")

    L += ["-" * 78, " worth a look", "-" * 78]
    L += sorted(set(flags)) if flags else [" (none — cadence, success, and memory all look nominal)"]

    L += ["", "-" * 78, " column key", "-" * 78,
          " runs      runs in the window; (NF) = N of them failed",
          " ok        success rate — % of runs that reached a clean 'completed' status",
          " emit*     emit rate — % of runs whose summary reads like it emitted. HEURISTIC",
          "           on the prose: can over-count when a summary recaps a PRIOR run's",
          "           emit. Confirm signal-to-noise against inbox-reports-list.",
          " gap/ival  median gap between consecutive run starts / the configured",
          "           run_interval_minutes. gap well above ival = the scout is being skipped.",
          " adher     cadence adherence — runs observed / runs expected across the window",
          "           span at that interval. 100% = fired on (nearly) every scheduled tick.",
          " med       median run duration (start -> finish). healthy runs finish in a couple",
          "           of minutes; a ~30m median is timeout-shaped over-investigation.",
          " mem       durable scratchpad entries attributed to this scout (via the run that",
          "           wrote them) in --scratchpad. 'n/a' = no --scratchpad passed; '0' = passed",
          "           but none matched (often the writing run falls outside the runs window)."]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", required=True, help="signals-scout-runs-list --json over a window")
    ap.add_argument("--config", help="signals-scout-config-list --json (for expected interval)")
    ap.add_argument("--scratchpad", help="signals-scout-scratchpad-search --json (for memory growth)")
    ap.add_argument("--now", help="ISO-8601 current time, for staleness")
    ap.add_argument("--skill", help="restrict to one scout skill_name")
    ap.add_argument("--no-art", dest="art", action="store_false", help="skip the hedgehog banner")
    ap.add_argument("--out", help="write here instead of stdout (use a .txt path)")
    args = ap.parse_args()

    run_rows = rows(load(args.runs))
    if args.skill:
        run_rows = [r for r in run_rows if r.get("skill_name") == args.skill]

    cfg_rows = rows(load(args.config)) if args.config else []
    intervals = {r.get("skill_name"): r.get("run_interval_minutes") for r in cfg_rows}
    last_run_by_skill = {r.get("skill_name"): r.get("last_run_at") for r in cfg_rows}
    now = parse_ts(args.now) if args.now else None

    # attribute scratchpad entries to a scout via the run that wrote them
    has_mem = bool(args.scratchpad)
    mem_by_skill: dict[str, int] = {}
    if has_mem:
        run_to_skill = {r.get("run_id"): r.get("skill_name") for r in run_rows}
        for entry in rows(load(args.scratchpad)):
            skill = run_to_skill.get(entry.get("created_by_run_id"))
            if skill:
                mem_by_skill[skill] = mem_by_skill.get(skill, 0) + 1

    by_skill: dict[str, list[dict]] = {}
    for r in run_rows:
        by_skill.setdefault(r.get("skill_name", "?"), []).append(r)

    assessed = [
        assess_scout(name, runs, intervals.get(name), (mem_by_skill.get(name, 0) if has_mem else None),
                     now, last_run_by_skill.get(name))
        for name, runs in by_skill.items()
    ]

    starts = [s for r in run_rows if (s := parse_ts(r.get("started_at")))]
    if starts:
        lo, hi = min(starts), max(starts)
        window_note = f"window: {lo:%Y-%m-%d %H:%M} -> {hi:%Y-%m-%d %H:%M} UTC · {len(run_rows)} runs across {len(assessed)} scout(s)."
    else:
        window_note = f"{len(run_rows)} runs across {len(assessed)} scout(s)."

    report = render(assessed, window_note, has_mem, art=args.art)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report + "\n")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
