#!/usr/bin/env python3
"""
Compute baseline statistics from `logs-count-ranges` output and suggest an alert
threshold scaled to a target alert window. Pure stdlib — no install needed.

Usage:
    cat count_ranges_output.json | baseline_stats.py --window-minutes 5
    baseline_stats.py --window-minutes 30 --floor 10 < count_ranges_output.json

Input (stdin): the JSON body returned by the `logs-count-ranges` tool, e.g.
    {
      "ranges": [
        {"date_from": "2026-04-22T00:00:00", "date_to": "2026-04-22T07:00:00", "count": 47},
        ...
      ],
      "interval": "7h"
    }

Output (stdout): JSON with `stats` (p50/p95/p99/max), `suggested_threshold_count`
scaled to the alert window, and a `health` field flagging baselines that are too
sparse, too flat, or too spiky to alert on usefully.

Exit codes:
    0  — stats produced
    1  — invalid input (no ranges, malformed JSON, etc.)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--window-minutes",
        type=int,
        required=True,
        choices=[5, 10, 15, 30, 60],
        help="Alert window in minutes (must match logs-alerts-create.window_minutes).",
    )
    p.add_argument(
        "--floor",
        type=int,
        default=5,
        help="Minimum threshold (default: 5). Stops the suggestion collapsing on tiny services.",
    )
    p.add_argument(
        "--min-buckets",
        type=int,
        default=12,
        help="Minimum non-empty buckets for a useful baseline (default: 12).",
    )
    return p.parse_args()


def parse_iso(s: str) -> datetime:
    # logs-count-ranges currently returns naive ISO; some clients add Z.
    cleaned = s.replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned)


def percentile(sorted_counts: list[int], q: float) -> float:
    # Matches numpy default (linear interpolation between nearest ranks).
    if not sorted_counts:
        return 0.0
    if len(sorted_counts) == 1:
        return float(sorted_counts[0])
    rank = q * (len(sorted_counts) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_counts) - 1)
    frac = rank - lo
    return sorted_counts[lo] * (1 - frac) + sorted_counts[hi] * frac


def main() -> int:
    args = parse_args()

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Could not parse stdin as JSON: {e}", file=sys.stderr)
        return 1

    ranges = data.get("ranges") if isinstance(data, dict) else None
    if not ranges:
        print(
            "No buckets in input — `ranges` is empty or missing. "
            "Either the filter matched nothing, or you piped the wrong response.",
            file=sys.stderr,
        )
        return 1

    counts = [r["count"] for r in ranges if isinstance(r, dict) and "count" in r]
    if not counts:
        print("Bucket entries are missing `count` fields.", file=sys.stderr)
        return 1

    try:
        first = ranges[0]
        bucket_minutes = (parse_iso(first["date_to"]) - parse_iso(first["date_from"])).total_seconds() / 60
    except (KeyError, ValueError) as e:
        print(f"Could not derive bucket width from first range: {e}", file=sys.stderr)
        return 1

    if bucket_minutes <= 0:
        print("Bucket width is non-positive — input looks corrupt.", file=sys.stderr)
        return 1

    sorted_counts = sorted(counts)
    n = len(counts)

    mid = n // 2
    p50 = float(sorted_counts[mid]) if n % 2 else (sorted_counts[mid - 1] + sorted_counts[mid]) / 2
    p95 = percentile(sorted_counts, 0.95)
    p99 = percentile(sorted_counts, 0.99)
    bucket_max = sorted_counts[-1]

    bucket_threshold = max(p99, p50 * 3, args.floor)
    scale = args.window_minutes / bucket_minutes
    suggested = max(args.floor, round(bucket_threshold * scale))

    health: list[str] = []
    if n < args.min_buckets:
        health.append(f"sparse:{n}_of_{args.min_buckets}_buckets")
    if bucket_max == 0:
        health.append("empty")
    elif p95 > 0 and bucket_max / p95 >= 10:
        health.append("spiky")
    elif p50 > 0 and (p95 / p50) <= 1.5:
        health.append("flat")

    output: dict[str, Any] = {
        "n_buckets": n,
        "bucket_minutes": round(bucket_minutes, 2),
        "alert_window_minutes": args.window_minutes,
        "stats": {
            "p50": round(p50, 2),
            "p95": round(p95, 2),
            "p99": round(p99, 2),
            "max": bucket_max,
        },
        "suggested_threshold_count": suggested,
        "rationale": (
            f"max(p99={round(p99, 2)}, median*3={round(p50 * 3, 2)}, floor={args.floor}) "
            f"scaled from {bucket_minutes:.0f}m bucket to {args.window_minutes}m window"
        ),
        "health": health,
    }

    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
