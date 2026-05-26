#!/usr/bin/env python3
"""Rank breakdown segments by absolute contribution to a metric delta.

Reads the JSON output of a `posthog:query-trends` call with `breakdownFilter`
on stdin or as a file path. The payload's `results` array contains one entry
per breakdown value, each with a `data` and `days` series.

Implements the "interpreting breakdown results" guidance from
shared-patterns.md: a 50% swing on a series that's 1% of volume only explains
0.5% of the aggregate delta. Sort by absolute contribution, not by percentage.

Usage:
    python3 scripts/breakdown_attribution.py < breakdown_result.json
    python3 scripts/breakdown_attribution.py breakdown_result.json

Optional env:
    WINDOW=N            How many trailing intervals (days/hours/etc., depending
                        on the input's interval) to treat as the anomaly window.
                        Default 7. The preceding N intervals are the baseline.
    TOP=N               Show only the top N segments (default 10).
"""

from __future__ import annotations

import json
import os
import sys


def load_input() -> dict:
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            raw = f.read()
    else:
        raw = sys.stdin.read()
    parsed = json.loads(raw)
    if isinstance(parsed, list) and parsed and parsed[0].get("type") == "text":
        parsed = json.loads(parsed[0]["text"])
    return parsed


def fmt(v: float, signed: bool = False) -> str:
    if signed:
        prefix = "+" if v >= 0 else "-"
    else:
        prefix = "" if v >= 0 else "-"
    a = abs(v)
    if a >= 1_000_000:
        return f"{prefix}{a / 1_000_000:.2f}M"
    if a >= 1_000:
        return f"{prefix}{a / 1_000:.1f}K"
    return f"{prefix}{a:,.0f}"


def fmt_pct(v: float) -> str:
    # `v == v` is False only when v is NaN.
    return f"{v:+.1f}%" if v == v else "n/a"


def main() -> int:
    window = int(os.environ.get("WINDOW", "7"))
    top = int(os.environ.get("TOP", "10"))

    payload = load_input()
    results = payload.get("results") or payload.get("result") or []
    if not results:
        raise SystemExit("No results in payload — is this a breakdown trends response?")

    rows = []
    total_anomaly = 0.0
    total_baseline = 0.0

    for series in results:
        data = series.get("data") or []
        if len(data) < 2 * window:
            print(
                f"warn: series '{series.get('breakdown_value', series.get('label'))}' "
                f"has {len(data)} points but window*2={2 * window} — "
                "skipping (extend dateRange).",
                file=sys.stderr,
            )
            continue
        baseline = sum(data[-2 * window : -window])
        current = sum(data[-window:])
        delta = current - baseline
        total_anomaly += current
        total_baseline += baseline

        seg = series.get("breakdown_value")
        if seg is None or seg == "":
            seg = series.get("label", "(none)")
        if isinstance(seg, list):
            seg = " / ".join(str(x) for x in seg)
        rows.append({
            "segment": str(seg),
            "baseline": baseline,
            "current": current,
            "delta": delta,
            "pct": (delta / baseline * 100) if baseline else float("nan"),
        })

    if not rows:
        raise SystemExit(
            "No usable series — every breakdown had fewer than 2 windows of data. "
            "Run with a wider dateRange."
        )

    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    total_delta = total_anomaly - total_baseline

    print(f"# Breakdown attribution — last {window} intervals vs preceding {window} intervals")
    print()
    print(f"Aggregate: {fmt(total_baseline)} → {fmt(total_anomaly)}  ({fmt(total_delta, signed=True)}, "
          f"{fmt_pct((total_delta / total_baseline * 100) if total_baseline else float('nan'))})")
    print()
    print("Segments ranked by **absolute** delta contribution:")
    print()
    print("| Segment | Baseline | Current | Δ | Δ% | Share of total Δ |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")

    for r in rows[:top]:
        share = (r["delta"] / total_delta * 100) if total_delta else float("nan")
        print(
            f"| {r['segment']} "
            f"| {fmt(r['baseline'])} "
            f"| {fmt(r['current'])} "
            f"| {fmt(r['delta'], signed=True)} "
            f"| {fmt_pct(r['pct'])} "
            f"| {fmt_pct(share)} |"
        )

    print()
    # If the aggregate barely moved but segments did, segments are offsetting.
    # That's a different diagnostic than "one segment absorbs the delta".
    aggregate_pct = (total_delta / total_baseline * 100) if total_baseline else 0
    largest_segment_move = max(abs(r["delta"]) for r in rows)
    aggregate_is_quiet = abs(aggregate_pct) < 5 and largest_segment_move > abs(total_delta) * 2

    if aggregate_is_quiet:
        print(
            "**Aggregate barely moved but individual segments did — segments are "
            "offsetting each other. Investigate the largest movers separately rather "
            "than as a 'share of total delta'.**"
        )
        return 0

    top_row = rows[0]
    top_share = (top_row["delta"] / total_delta * 100) if total_delta else float("nan")
    if total_delta and abs(top_share) >= 50:
        print(
            f"**Top segment '{top_row['segment']}' absorbs "
            f"{abs(top_share):.0f}% of the aggregate delta — strong segment signal.**"
        )
    elif total_delta and sum(abs(r["delta"]) for r in rows[:3]) / abs(total_delta) >= 0.7:
        print(
            "**Top 3 segments account for ≥70% of the delta — investigate what they share.**"
        )
    else:
        print(
            "**No single segment dominates — the cause is likely system-wide "
            "(deploy, tracking, infra) rather than segment-specific.**"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
