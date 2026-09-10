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

A bucket that has not finished yet covers less elapsed time than the buckets it is
compared to, so its value is always low and says nothing about the metric. Every
unfinished bucket is reported as partial and left out of the anomaly counts. That
is decided from the clock, never from the size of the drop.

Bucket starts are placed on the real timeline using the project's UTC offset, which
`action.days` and the `filter` bounds both carry. Pass the query tool's whole JSON
response so that offset survives. If no offset is present anywhere, the timestamps
are read as UTC, which can misjudge a bucket close to its boundary.

Optional env:
    TOLERANCE=N.NN  Fraction outside prior min/max counted as still "in range"
                    (default 0.10 — i.e. 10% wiggle on each side of the band).
    TOP=N           For hourly output, how many most-deviated points to show
                    (default 10).
    RECENT=N        How many recent intervals to evaluate (default: one cycle).
    NOW=<iso8601>   Instant to treat as "now" when deciding which buckets have
                    finished (default: the system clock).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone, tzinfo
from statistics import median

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

INTERVAL_STEPS = {
    "second": timedelta(seconds=1),
    "minute": timedelta(minutes=1),
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
}

SUB_DAY_INTERVALS = {"second", "minute", "hour"}


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


def extract_series(payload: dict) -> tuple[list[tuple[datetime, float]], str, str]:
    """Return (points, label, interval)."""
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
    return build_points(series, data), label, interval


def build_points(series: dict, data: list[float]) -> list[tuple[datetime, float]]:
    """Pair each bucket start with its value, keeping the project's UTC offset.

    `days` holds bare dates, but `action.days` holds the same starts with the
    project's offset, which is needed to place a bucket on the real timeline.
    """
    stamps = (series.get("action") or {}).get("days") or []
    if len(stamps) != len(data):
        stamps = series.get("days") or []
    zone = series_tzinfo(series) or timezone.utc

    points: list[tuple[datetime, float]] = []
    for raw, value in zip(stamps, data):
        dt = parse_dt(raw)
        if dt is None:
            continue
        points.append((dt if dt.tzinfo is not None else dt.replace(tzinfo=zone), value))
    return points


def series_tzinfo(series: dict) -> tzinfo | None:
    """The project's UTC offset, read off whichever filter bound carries one."""
    bounds = series.get("filter") or {}
    for key in ("date_from", "date_to"):
        parsed = parse_dt(bounds.get(key) or "")
        if parsed is not None and parsed.tzinfo is not None:
            return parsed.tzinfo
    return None


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


def stamp(dt: datetime, interval: str) -> str:
    """Bucket label, carrying time-of-day only where the interval needs it."""
    if interval in SUB_DAY_INTERVALS:
        return dt.strftime("%Y-%m-%d %H:%M")
    return dt.strftime("%Y-%m-%d")


def next_bucket_start(dt: datetime, interval: str) -> datetime:
    """Start of the bucket after the one beginning at dt."""
    if interval == "month":
        year, month = (dt.year + 1, 1) if dt.month == 12 else (dt.year, dt.month + 1)
        return dt.replace(year=year, month=month, day=1)
    return dt + INTERVAL_STEPS.get(interval, timedelta(days=1))


def resolve_now() -> datetime:
    """The instant that decides which buckets have finished."""
    override = os.environ.get("NOW")
    now = parse_dt(override) if override else None
    if now is None:
        return datetime.now(timezone.utc)
    return now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)


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


def judge(
    dt: datetime,
    value: float,
    priors: list[float],
    tolerance: float,
    interval: str,
    now: datetime,
) -> tuple[str, float, bool]:
    """Return (verdict, deviation_pct, partial) for one bucket.

    An unfinished bucket is not compared at all, because its value reflects how
    much of the period has elapsed rather than the metric.
    """
    if now < next_bucket_start(dt, interval):
        return f"PARTIAL (this {interval} has not finished)", 0.0, True
    verdict, dev = classify(value, priors, tolerance)
    return verdict, dev, False


def partial_note(n_partial: int, interval: str) -> str:
    """Trailing sentence for the verdict, naming what was left out."""
    if not n_partial:
        return ""
    if n_partial == 1:
        return f" The last {interval} has not finished, so it was left out of the count."
    return (
        f" The last {n_partial} {interval}s have not finished, so they were left out "
        "of the count."
    )


def compare_cycle_keyed(
    points: list[tuple[datetime, float]],
    cycle_len: int,
    key_fn,
    tolerance: float,
    interval: str,
    now: datetime,
) -> tuple[list[dict], int, int]:
    """Group prior points by cycle key, compare recent points to their bucket.

    Returns (results, in_range_count, out_of_range_count). Unfinished buckets
    land in neither count.
    """
    if len(points) < cycle_len * 2:
        return [], 0, 0
    recent = points[-cycle_len:]
    priors = points[:-cycle_len]

    grouped: dict = {}
    for dt, v in priors:
        grouped.setdefault(key_fn(dt), []).append(v)

    out: list[dict] = []
    in_range = out_of_range = 0
    for dt, v in recent:
        key = key_fn(dt)
        prior_vals = grouped.get(key, [])
        verdict, dev, partial = judge(dt, v, prior_vals, tolerance, interval, now)
        if not partial:
            if "in range" in verdict:
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
            "partial": partial,
        })
    return out, in_range, out_of_range


def report_day_cycle(
    label: str, points: list[tuple[datetime, float]], tolerance: float, now: datetime
) -> None:
    results, in_range, out_of_range = compare_cycle_keyed(
        points,
        cycle_len=7,
        key_fn=lambda dt: dt.weekday(),
        tolerance=tolerance,
        interval="day",
        now=now,
    )

    print(f"# Same-day-of-week comparison — {label}")
    print()
    print(
        f"Window: {stamp(points[0][0], 'day')} → {stamp(points[-1][0], 'day')}  "
        f"({len(points)} days)"
    )
    print(f"Cycle: weekly  (each weekday compared to prior {(len(points) // 7) - 1} same-weekdays)")
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
    note = partial_note(sum(r["partial"] for r in results), "day")
    if in_range == 0 and out_of_range == 0:
        print("**Verdict: no completed weekday was available to compare.**" + note)
    elif out_of_range == 0:
        print(
            f"**Verdict: every completed weekday is within ±{tolerance:.0%} of the "
            "prior weeks' range — likely normal seasonality.**" + note
        )
    else:
        print(
            f"**Verdict: {out_of_range} completed weekday(s) outside the prior weeks' "
            f"range (±{tolerance:.0%} tolerance) — proceed with the playbook.**" + note
        )


def report_hour_cycle(
    label: str,
    points: list[tuple[datetime, float]],
    tolerance: float,
    top: int,
    now: datetime,
) -> None:
    results, in_range, out_of_range = compare_cycle_keyed(
        points,
        cycle_len=168,
        key_fn=lambda dt: (dt.weekday(), dt.hour),
        tolerance=tolerance,
        interval="hour",
        now=now,
    )

    print(f"# Same-hour-of-week comparison — {label}")
    print()
    print(f"Window: {stamp(points[0][0], 'hour')} → {stamp(points[-1][0], 'hour')}  "
          f"({len(points)} hours, ~{len(points) / 168:.1f} weeks)")
    print(f"Cycle: weekly × hourly (168 buckets, each hour vs prior weeks' same weekday-hour)")
    print()
    if not results:
        print("Not enough history — need at least 2 full weeks of hourly data. Widen the dateRange.")
        return

    note = partial_note(sum(r["partial"] for r in results), "hour")
    print(f"Last 168 hours: **{in_range} in range, {out_of_range} outside ±{tolerance:.0%}**")
    print()

    flagged = [
        r for r in results
        if "in range" not in r["verdict"] and not r["partial"]
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
    if in_range == 0 and out_of_range == 0:
        print("**Verdict: no completed hour was available to compare.**" + note)
    elif out_of_range == 0:
        print(
            f"**Verdict: every completed hour in the last week is within ±{tolerance:.0%} of "
            "prior weeks — likely normal seasonality.**" + note
        )
    else:
        if out_of_range / max(1, in_range + out_of_range) > 0.5:
            print(
                f"**Verdict: >50% of completed hours are out of range — likely a sustained "
                "shift, not a localized incident. Proceed with the playbook.**" + note
            )
        else:
            print(
                f"**Verdict: {out_of_range} flagged hours concentrated in the table above. "
                "Check whether they cluster around a deploy time / incident — "
                "see SKILL.md step 2.3.**" + note
            )


def report_sequential(
    label: str,
    points: list[tuple[datetime, float]],
    interval: str,
    recent_n: int,
    tolerance: float,
    now: datetime,
) -> None:
    """Sequential comparison for week / month / minute — no natural cycle."""
    if len(points) < recent_n + 3:
        print(f"# Sequential comparison — {label}", flush=True)
        print()
        print(
            f"Not enough history for {interval} interval — need at least "
            f"{recent_n + 3} points; have {len(points)}. Widen the dateRange."
        )
        return

    recent = points[-recent_n:]
    priors = [v for _, v in points[:-recent_n]]
    prior_med = median(priors)
    lo, hi = min(priors), max(priors)

    print(f"# Sequential comparison — {label}")
    print()
    print(
        f"Window: {stamp(points[0][0], interval)} → {stamp(points[-1][0], interval)}  "
        f"({len(points)} {interval} intervals). No natural cycle for {interval} — "
        f"comparing last {recent_n} to prior {len(priors)} values."
    )
    print()
    print(f"Prior median: {fmt(prior_med)}  |  range: {fmt(lo)} – {fmt(hi)}")
    print()
    print(f"| {interval.title()} | Value | Verdict |")
    print("| --- | ---: | --- |")
    out_of_range = 0
    in_range = 0
    n_partial = 0
    for dt, v in recent:
        verdict, _, partial = judge(dt, v, priors, tolerance, interval, now)
        if partial:
            n_partial += 1
        elif "in range" in verdict:
            in_range += 1
        else:
            out_of_range += 1
        print(f"| {stamp(dt, interval)} | {fmt(v)} | {verdict} |")
    print()
    note = partial_note(n_partial, interval)
    if in_range == 0 and out_of_range == 0:
        print(f"**Verdict: no completed {interval} was available to compare.**" + note)
    elif out_of_range == 0:
        print(
            f"**Verdict: all completed {interval}s within ±{tolerance:.0%} of the prior "
            "range — within normal variance.**" + note
        )
    else:
        print(f"**Verdict: {out_of_range} of {recent_n - n_partial} completed recent "
              f"{interval}s outside the prior range — proceed with the playbook.**" + note)


def main() -> int:
    tolerance = float(os.environ.get("TOLERANCE", "0.10"))
    top = int(os.environ.get("TOP", "10"))
    recent_override = os.environ.get("RECENT")
    now = resolve_now()

    payload = load_input()
    points, label, interval = extract_series(payload)

    if not points:
        print("Empty series — nothing to compare.", file=sys.stderr)
        return 1

    if interval == "day":
        report_day_cycle(label, points, tolerance, now)
    elif interval == "hour":
        report_hour_cycle(label, points, tolerance, top, now)
    elif interval in {"minute", "second"}:
        recent_n = int(recent_override) if recent_override else 60
        report_sequential(label, points, interval, recent_n, tolerance, now)
    elif interval == "week":
        recent_n = int(recent_override) if recent_override else 4
        report_sequential(label, points, interval, recent_n, tolerance, now)
    elif interval == "month":
        recent_n = int(recent_override) if recent_override else 3
        report_sequential(label, points, interval, recent_n, tolerance, now)
    else:
        print(f"Unsupported interval '{interval}'. Treating as sequential.", file=sys.stderr)
        recent_n = int(recent_override) if recent_override else 7
        report_sequential(label, points, interval, recent_n, tolerance, now)

    return 0


if __name__ == "__main__":
    sys.exit(main())
