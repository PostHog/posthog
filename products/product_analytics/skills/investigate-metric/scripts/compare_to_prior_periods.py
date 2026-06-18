#!/usr/bin/env python3
"""Compare a recent series to comparable prior periods, accounting for cycles.

Reads the JSON output of a `posthog:query-trends` (or similar) call on stdin or
as a file path. Auto-detects interval and picks the right cycle:

    minute → no cycle, rolling (last N vs preceding N)
    hour   → weekly cycle (168 buckets, weekday × hour-of-day)
    day    → weekly cycle (7 buckets, weekday)
    week   → no cycle, sequential
    month  → no cycle, sequential

Use after step 2.1 of SKILL.md to resolve the variance question (step 2.2).

Usage:
    python3 scripts/compare_to_prior_periods.py < query_result.json
    python3 scripts/compare_to_prior_periods.py query_result.json

Optional env:
    TOLERANCE=N.NN  Fraction outside prior min/max counted as still "in range"
                    (default 0.10 — i.e. 10% wiggle on each side of the band).
    TOP=N           For hourly output, how many most-deviated points to show
                    (default 10).
    RECENT=N        How many recent intervals to evaluate (default: one cycle).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from statistics import median


WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


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


def extract_series(payload: dict) -> tuple[list[str], list[float], str, str]:
    """Return (days, data, label, interval)."""
    results = payload.get("results") or payload.get("result") or []
    if not results:
        raise SystemExit("No results in payload — is this a trends query response?")
    series = results[0]
    days = series.get("days") or []
    data = series.get("data") or []
    label = series.get("label") or series.get("custom_name") or "metric"

    interval = (series.get("filter") or {}).get("interval")
    if not interval:
        interval = (payload.get("query") or {}).get("interval")
    if not interval:
        interval = infer_interval_from_days(days)

    if len(days) != len(data):
        raise SystemExit(f"days ({len(days)}) and data ({len(data)}) length mismatch")
    return days, data, label, interval


def infer_interval_from_days(days: list[str]) -> str:
    """Best-effort interval detection from the gap between days[0] and days[1]."""
    if len(days) < 2:
        return "day"
    a = parse_dt(days[0])
    b = parse_dt(days[1])
    if a is None or b is None:
        return "day"
    delta = abs((b - a).total_seconds())
    if delta < 120:
        return "minute"
    if delta < 7200:
        return "hour"
    if delta < 60 * 60 * 30:  # < ~30 hours = day
        return "day"
    if delta < 60 * 60 * 24 * 10:
        return "week"
    return "month"


def parse_dt(s: str) -> datetime | None:
    s = s.replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def fmt(v: float) -> str:
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1_000_000:
        return f"{sign}{a / 1_000_000:.2f}M"
    if a >= 1_000:
        return f"{sign}{a / 1_000:.1f}K"
    return f"{sign}{a:,.0f}"


def classify(value: float, prior: list[float], tolerance: float) -> tuple[str, float]:
    """Return (verdict, deviation_pct).

    deviation_pct is signed; 0 means inside the prior min/max band.
    """
    if not prior:
        return "no priors", 0.0
    lo, hi = min(prior), max(prior)
    lo_band = lo * (1 - tolerance)
    hi_band = hi * (1 + tolerance)
    if lo_band <= value <= hi_band:
        return "in range", 0.0
    if value < lo_band:
        pct = (value - lo) / lo * 100 if lo else 0
        return f"BELOW ({pct:+.0f}% vs min)", pct
    pct = (value - hi) / hi * 100 if hi else 0
    return f"ABOVE ({pct:+.0f}% vs max)", pct


def compare_cycle_keyed(
    points: list[tuple[datetime, float]],
    cycle_len: int,
    key_fn,
    tolerance: float,
) -> tuple[list[dict], int, int]:
    """Group prior points by cycle key, compare recent points to their bucket.

    Returns (results, in_range_count, out_of_range_count).
    """
    if len(points) < cycle_len * 2:
        return [], 0, 0
    recent = points[-cycle_len:]
    priors = points[:-cycle_len]

    grouped: dict = {}
    for dt, v in priors:
        grouped.setdefault(key_fn(dt), []).append(v)

    last_dt = recent[-1][0]
    out: list[dict] = []
    in_range = out_of_range = partial = 0
    for dt, v in recent:
        key = key_fn(dt)
        prior_vals = grouped.get(key, [])
        verdict, dev = classify(v, prior_vals, tolerance)
        # Soften: if this is the very last bucket and it's >=50% below prior min,
        # it's almost certainly a partial period (incomplete day / hour).
        is_last = dt == last_dt
        if (
            is_last
            and prior_vals
            and "BELOW" in verdict
            and v < min(prior_vals) * 0.5
        ):
            verdict = f"PARTIAL? ({(v - min(prior_vals)) / min(prior_vals) * 100:+.0f}% vs min)"
            partial += 1
        elif "in range" in verdict:
            in_range += 1
        elif prior_vals:
            out_of_range += 1
        out.append({
            "dt": dt,
            "key": key,
            "value": v,
            "prior_min": min(prior_vals) if prior_vals else None,
            "prior_max": max(prior_vals) if prior_vals else None,
            "prior_median": median(prior_vals) if prior_vals else None,
            "n_prior": len(prior_vals),
            "verdict": verdict,
            "deviation": abs(dev),
            "partial": "PARTIAL?" in verdict,
        })
    return out, in_range, out_of_range


def report_day_cycle(label: str, days: list[str], data: list[float], tolerance: float) -> None:
    points: list[tuple[datetime, float]] = [
        (dt, v) for d, v in zip(days, data) if (dt := parse_dt(d)) is not None
    ]

    results, in_range, out_of_range = compare_cycle_keyed(
        points, cycle_len=7, key_fn=lambda dt: dt.weekday(), tolerance=tolerance
    )

    print(f"# Same-day-of-week comparison — {label}")
    print()
    print(f"Window: {days[0]} → {days[-1]}  ({len(days)} days)")
    print(f"Cycle: weekly  (each weekday compared to prior {(len(days) // 7) - 1} same-weekdays)")
    print()
    if not results:
        print("Not enough history — need at least 2 full weeks. Widen the dateRange.")
        return

    print("| Day | Most recent | Prior median | Prior range | Verdict |")
    print("| --- | ---: | ---: | --- | --- |")
    for r in results:
        prior_range = (
            f"{fmt(r['prior_min'])} – {fmt(r['prior_max'])}" if r["prior_min"] is not None else "—"
        )
        print(
            f"| {WEEKDAYS[r['key']]} {r['dt'].date()} "
            f"| {fmt(r['value'])} "
            f"| {fmt(r['prior_median']) if r['prior_median'] is not None else '—'} "
            f"| {prior_range} "
            f"| {r['verdict']} |"
        )

    print()
    has_partial = any(r.get("partial") for r in results)
    if out_of_range == 0 and in_range > 0:
        msg = (
            f"**Verdict: every completed weekday is within ±{tolerance:.0%} of the "
            "prior weeks' range — likely normal seasonality.**"
        )
        if has_partial:
            msg += " The last day looks partial; ignore it for now and re-check after it completes."
        print(msg)
    elif out_of_range > 0:
        print(
            f"**Verdict: {out_of_range} completed weekday(s) outside the prior weeks' "
            f"range (±{tolerance:.0%} tolerance) — proceed with the playbook.**"
        )
        if has_partial:
            print("(The last day appears partial and was excluded from the count.)")


def report_hour_cycle(
    label: str, days: list[str], data: list[float], tolerance: float, top: int
) -> None:
    points: list[tuple[datetime, float]] = [
        (dt, v) for d, v in zip(days, data) if (dt := parse_dt(d)) is not None
    ]

    results, in_range, out_of_range = compare_cycle_keyed(
        points,
        cycle_len=168,
        key_fn=lambda dt: (dt.weekday(), dt.hour),
        tolerance=tolerance,
    )

    print(f"# Same-hour-of-week comparison — {label}")
    print()
    print(f"Window: {days[0]} → {days[-1]}  ({len(days)} hours, "
          f"~{len(days) / 168:.1f} weeks)")
    print(f"Cycle: weekly × hourly (168 buckets, each hour vs prior weeks' same weekday-hour)")
    print()
    if not results:
        print("Not enough history — need at least 2 full weeks of hourly data. Widen the dateRange.")
        return

    print(f"Last 168 hours: **{in_range} in range, {out_of_range} outside ±{tolerance:.0%}**")
    print()

    flagged = [
        r for r in results
        if "in range" not in r["verdict"] and not r.get("partial")
    ]
    flagged.sort(key=lambda r: r["deviation"], reverse=True)

    if flagged:
        print(f"## Top {min(top, len(flagged))} most deviated hours")
        print()
        print("| Time | Value | Prior median | Prior range | Verdict |")
        print("| --- | ---: | ---: | --- | --- |")
        for r in flagged[:top]:
            wd, hr = r["key"]
            prior_range = (
                f"{fmt(r['prior_min'])} – {fmt(r['prior_max'])}" if r["prior_min"] is not None else "—"
            )
            print(
                f"| {WEEKDAYS[wd]} {hr:02d}:00 ({r['dt'].strftime('%Y-%m-%d')}) "
                f"| {fmt(r['value'])} "
                f"| {fmt(r['prior_median']) if r['prior_median'] is not None else '—'} "
                f"| {prior_range} "
                f"| {r['verdict']} |"
            )
        print()

        # Aggregate where the flags concentrate
        by_weekday: dict[int, int] = {}
        by_hour: dict[int, int] = {}
        for r in flagged:
            wd, hr = r["key"]
            by_weekday[wd] = by_weekday.get(wd, 0) + 1
            by_hour[hr] = by_hour.get(hr, 0) + 1

        if by_weekday:
            print("## Flags by weekday")
            print()
            for wd in sorted(by_weekday, key=lambda k: -by_weekday[k]):
                print(f"- {WEEKDAYS[wd]}: {by_weekday[wd]}")
            print()
        if by_hour:
            print("## Flags by hour-of-day")
            print()
            for hr in sorted(by_hour, key=lambda k: -by_hour[k])[:10]:
                print(f"- {hr:02d}:00 — {by_hour[hr]}")
            print()

    print()
    if out_of_range == 0 and in_range > 0:
        print(
            f"**Verdict: every hour in the last week is within ±{tolerance:.0%} of "
            "prior weeks — likely normal seasonality.**"
        )
    elif out_of_range > 0:
        if out_of_range / max(1, in_range + out_of_range) > 0.5:
            print(
                f"**Verdict: >50% of hours are out of range — likely a sustained shift, "
                "not a localized incident. Proceed with the playbook.**"
            )
        else:
            print(
                f"**Verdict: {out_of_range} flagged hours concentrated in the table above. "
                "Check whether they cluster around a deploy time / incident — "
                "see SKILL.md step 2.3.**"
            )


def report_sequential(
    label: str,
    days: list[str],
    data: list[float],
    interval: str,
    recent_n: int,
    tolerance: float,
) -> None:
    """Sequential comparison for week / month / minute — no natural cycle."""
    if len(data) < recent_n + 3:
        print(f"# Sequential comparison — {label}", flush=True)
        print()
        print(
            f"Not enough history for {interval} interval — need at least "
            f"{recent_n + 3} points; have {len(data)}. Widen the dateRange."
        )
        return

    recent = list(zip(days[-recent_n:], data[-recent_n:]))
    priors = data[:-recent_n]
    prior_med = median(priors)
    lo, hi = min(priors), max(priors)

    print(f"# Sequential comparison — {label}")
    print()
    print(
        f"Window: {days[0]} → {days[-1]}  ({len(days)} {interval} intervals). "
        f"No natural cycle for {interval} — comparing last {recent_n} to "
        f"prior {len(priors)} values."
    )
    print()
    print(f"Prior median: {fmt(prior_med)}  |  range: {fmt(lo)} – {fmt(hi)}")
    print()
    print(f"| {interval.title()} | Value | Verdict |")
    print("| --- | ---: | --- |")
    out_of_range = 0
    in_range = 0
    for d, v in recent:
        verdict, _ = classify(v, priors, tolerance)
        if "in range" in verdict:
            in_range += 1
        else:
            out_of_range += 1
        print(f"| {d} | {fmt(v)} | {verdict} |")
    print()
    if out_of_range == 0:
        print(
            f"**Verdict: all recent {interval}s within ±{tolerance:.0%} of the prior "
            "range — within normal variance.**"
        )
    else:
        print(f"**Verdict: {out_of_range} of {recent_n} recent {interval}s outside the "
              f"prior range — proceed with the playbook.**")


def main() -> int:
    tolerance = float(os.environ.get("TOLERANCE", "0.10"))
    top = int(os.environ.get("TOP", "10"))
    recent_override = os.environ.get("RECENT")

    payload = load_input()
    days, data, label, interval = extract_series(payload)

    if not days:
        print("Empty series — nothing to compare.", file=sys.stderr)
        return 1

    if interval == "day":
        report_day_cycle(label, days, data, tolerance)
    elif interval == "hour":
        report_hour_cycle(label, days, data, tolerance, top)
    elif interval in {"minute", "second"}:
        recent_n = int(recent_override) if recent_override else 60
        report_sequential(label, days, data, interval, recent_n, tolerance)
    elif interval == "week":
        recent_n = int(recent_override) if recent_override else 4
        report_sequential(label, days, data, interval, recent_n, tolerance)
    elif interval == "month":
        recent_n = int(recent_override) if recent_override else 3
        report_sequential(label, days, data, interval, recent_n, tolerance)
    else:
        print(f"Unsupported interval '{interval}'. Treating as sequential.", file=sys.stderr)
        recent_n = int(recent_override) if recent_override else 7
        report_sequential(label, days, data, interval, recent_n, tolerance)

    return 0


if __name__ == "__main__":
    sys.exit(main())
