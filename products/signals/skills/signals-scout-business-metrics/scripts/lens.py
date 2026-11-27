#!/usr/bin/env python3
"""Lens and decomposition arithmetic for the business-metrics scout, pure stdlib.

Reads a JSON request on stdin and prints a JSON verdict, so the scout feeds the rows it read
and reads a verdict instead of computing medians under a token budget. No numpy needed.

Modes (request `mode`):
  - "judge": score the latest complete period of a series against its baseline.
      {"mode": "judge", "grain": "daily" | "weekly" | "monthly" | "quarterly",
       "series": [["2026-10-01", 81609], ...],
       "count_basis": true,
       "counts": [["2026-10-01", 81609], ...]}
    `series` holds [period start, value] pairs in any order; the last period must be complete.
    A period with a null value is dropped: a gap is missing data, not a zero.
    The 20-unit floor applies to counts only: set `count_basis` when the series itself is a
    count, or pass `counts`, a parallel count series, when the measure is money or a ratio.
    With neither, no floor applies.
    Every grain answers with the same shape: a `step` block and a `drift` block, each with
    `expected`, `deviation_pct`, `bar_pct`, `report_bar_pct`, `clears_report_bar` and `verdict`,
    plus the step fields mirrored at the top level and one overall `verdict`.
    Daily: step = latest day vs the 28-day median and the same-weekday median; drift = the last
    7 days vs the 4 prior weeks. Weekly, monthly, quarterly: step = latest closed period vs a trend
    expectation (the median of the 3 prior periods grown at the median period-over-period change)
    under a bar of 20% or twice the series' usual swing; drift = the last 3 periods vs the 3
    before, trend-adjusted, at 10% or one and a half times the swing. `long_trend` marks a move
    that continues a visible run; `seasonal_match` marks a period move the same period a year
    earlier also made.

      Invented example, monthly: the 6 prior months are 980, 1,050, 1,120, 1,210, 1,280 and 1,370,
      so the changes are +7%, +7%, +8%, +6% and +7%, growth 7%, swing 7%, bar 20%, level 1,280
      and expected 1,280 x 1.07^2 = 1,465. A latest month of 1,520 is +4%: within. 1,880 is +28%:
      a move.

  - "decompose": attribute a move to segments.
      {"mode": "decompose", "kind": "sum", "count_basis": true,
       "segments": [{"name": "pro", "cur": 120, "base": 100, "base_count": 40}, ...]}
      {"mode": "decompose", "kind": "ratio",
       "segments": [{"name": "pro", "num_cur": 12, "den_cur": 100,
                     "num_base": 10, "den_base": 90}, ...]}
    `cur` is the current window, `base` the average base period. For a ratio the mix effect is
    the segment's share of the denominator changing (measured against the overall base ratio, so a
    growing low-rate segment pulls the ratio down), the rate effect its own ratio changing.
    The verdict is `driver`, `broad`, `offsetting` (segments pulled both ways; the pushing and
    pulling segments are named) or `none`. `small_base` flags a segment under 20 units: for a sum
    set `count_basis` when the measure is a count, or give each segment a `base_count`.

  - "concentrate": whether a few entities carry a move, on a table with one row per entity
    and period (a customer-month view), where no low-cardinality dimension exists.
      {"mode": "concentrate", "total_cur": 64000, "total_base": 50000,
       "entities": [{"name": "acct_17", "cur": 9500, "base": 900}, ...]}
    `entities` holds the top 20 by absolute delta; the totals cover every entity. The verdict is
    `driver` when at most 5 entities moving with the move carry 60% of it, else `none`, the same
    words as `decompose`, so it copies into the record unchanged.

`rate: true` on a judge request marks a rate (a retention, a conversion, a margin): its bars
scale with its own swing above small floors (step 3%, drift 2% per period; 5% and 3% daily),
because a rate moving 20% in one period is a collapse, not the first sign of one. A request may
carry a `name`, echoed on its result.

`clears_report_bar` at the top level is either lens; `report_lens` names the one that clears it,
and each lens block carries `windows`, the `cur` and `base` ranges it compared, half-open
(`[start, end)`, the end being the start of the next period), which the decomposition reads.

The product-analytics `investigate-metric` skill ships `scripts/breakdown_attribution.py`, which
attributes a trends breakdown with its own thresholds (top-1 at 50%, top-3 at 70%). This script
takes table rows and ratios too, so the two stay separate; a change to one bar should visit both.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from statistics import median as _median

STEP_BAR = 0.30
DRIFT_BAR = 0.15
PERIOD_BAR = 0.20
PERIOD_DRIFT_BAR = 0.10
STEP_SWING_FACTOR = 2.0
DRIFT_SWING_FACTOR = 1.5
REPORT_BAR_FACTOR = 1.5
# A rate (a retention, a conversion, a margin) moves a few percent when something real happens,
# so its bars scale with its own swing above these small floors instead of the count bars.
RATE_STEP_BAR = 0.05
RATE_DRIFT_BAR = 0.03
RATE_PERIOD_BAR = 0.03
RATE_PERIOD_DRIFT_BAR = 0.02
RATE_DAILY_SWING_FACTOR = 3.0
UNIT_FLOOR = 20
BASE_PERIODS = {"weekly": 8, "monthly": 6, "quarterly": 4}
# Periods back to the same period a year earlier. Weekly has none: a 13-week window cannot hold one.
SEASON_PERIODS = {"monthly": 12, "quarterly": 4}
DRIVER_SHARE = 0.60
CONCENTRATION_ENTITIES = 5


def _pct(value: float) -> float:
    return round(value * 100, 1)


def _parse_series(rows: list) -> list[tuple[date, float]]:
    """Sort the rows by period and drop a period with no value: a gap is missing data, not a zero."""
    parsed = [(date.fromisoformat(str(day)[:10]), float(value)) for day, value in rows if value is not None]
    parsed.sort(key=lambda pair: pair[0])
    return parsed


def _floor_ok(counts: dict[date, float] | None, day: date, reference_days: list[date]) -> bool:
    """The 20-unit floor on the count behind a move. No counts means no floor."""
    if counts is None:
        return True
    reference = [counts[d] for d in reference_days if d in counts]
    return max(counts.get(day, 0.0), _median(reference) if reference else 0.0) >= UNIT_FLOOR


def _lens(value: float, expected: float, bar: float, passes: bool, **extra) -> dict:
    """One lens block: the expectation, the deviation, the bar, the report bar and the verdict."""
    deviation = value / expected - 1 if expected else 0.0
    return {
        "expected": round(expected, 2),
        "deviation_pct": _pct(deviation),
        "bar_pct": _pct(bar),
        "report_bar_pct": _pct(bar * REPORT_BAR_FACTOR),
        "clears_report_bar": passes and abs(deviation) >= bar * REPORT_BAR_FACTOR,
        "verdict": "move" if passes else "within",
        **extra,
    }


def _insufficient(reason: str) -> dict:
    return {"verdict": "insufficient history", "reason": reason}


def _next_period(day: date, grain: str) -> date:
    if grain == "daily":
        return day + timedelta(days=1)
    if grain == "weekly":
        return day + timedelta(days=7)
    months = 3 if grain == "quarterly" else 1
    month = day.month - 1 + months
    return date(day.year + month // 12, month % 12 + 1, 1)


def _window(start: date, last: date, grain: str) -> list[str]:
    """A half-open range, the first period's start to the start of the period after the last one,
    so the end drops straight into a `< end` predicate."""
    return [start.isoformat(), _next_period(last, grain).isoformat()]


def _combine(result: dict, step: dict, drift: dict) -> dict:
    """The step fields are mirrored at the top level, so a record reads the same at every grain.

    `clears_report_bar` is either lens: a slide that only the drift lens sees is as reportable as
    a step. `report_lens` names the lens that clears it, step first, and its `windows` are the
    ones the decomposition must read, so two runs attribute the same move over the same periods.
    """
    result["step"] = step
    result["drift"] = drift
    for key in ("expected", "deviation_pct", "bar_pct", "report_bar_pct"):
        if key in step:
            result[key] = step[key]
    step_clears = bool(step.get("clears_report_bar"))
    drift_clears = bool(drift.get("clears_report_bar"))
    result["clears_report_bar"] = step_clears or drift_clears
    result["report_lens"] = "step" if step_clears else "drift" if drift_clears else None
    result["step_verdict"] = step["verdict"]
    result["verdict"] = "move" if "move" in (step["verdict"], drift["verdict"]) else "within"
    return result


def judge_daily(series: list[tuple[date, float]], counts: dict[date, float] | None, rate: bool = False) -> dict:
    by_day = dict(series)
    day, value = series[-1]
    result: dict = {"grain": "daily", "period": day.isoformat(), "value": value}
    prior_days = [d for d, _ in series if day - timedelta(days=28) <= d < day]
    if len(prior_days) < 14:
        return {**result, **_insufficient(f"{len(prior_days)} prior days, 14 needed")}

    median_28d = _median([by_day[d] for d in prior_days])
    same_weekdays = [day - timedelta(days=7 * k) for k in (1, 2, 3, 4) if day - timedelta(days=7 * k) in by_day]
    median_same_weekday = _median([by_day[d] for d in same_weekdays]) if len(same_weekdays) >= 3 else median_28d
    step_bar, drift_bar, swing = STEP_BAR, DRIFT_BAR, None
    if rate and median_28d:
        # The median absolute deviation of the 28 days, relative to their median: the rate's daily noise.
        swing = _median([abs(by_day[d] - median_28d) for d in prior_days]) / median_28d
        step_bar = max(RATE_STEP_BAR, RATE_DAILY_SWING_FACTOR * swing)
        drift_bar = max(RATE_DRIFT_BAR, DRIFT_SWING_FACTOR * swing)
    step_pass = (
        median_28d > 0
        and median_same_weekday > 0
        and abs(value - median_28d) >= step_bar * median_28d
        and abs(value - median_same_weekday) >= step_bar * median_same_weekday
        and _floor_ok(counts, day, prior_days)
    )
    step_base = same_weekdays if len(same_weekdays) >= 3 else prior_days
    step = _lens(
        value,
        median_28d,
        step_bar,
        step_pass,
        median_same_weekday=round(median_same_weekday, 2),
        windows={"cur": _window(day, day, "daily"), "base": _window(min(step_base), max(step_base), "daily")},
        **({"swing_pct": _pct(swing)} if swing is not None else {}),
    )

    weeks = []
    for k in range(5):
        end = day - timedelta(days=7 * k)
        days = [end - timedelta(days=i) for i in range(7)]
        weeks.append(sum(by_day[d] for d in days) if all(d in by_day for d in days) else None)
    if any(w is None for w in weeks):
        drift = _insufficient("fewer than 5 complete weeks")
    else:
        if rate:
            # A rate's week is its daily average, not a sum, so the drift reads in rate points.
            weeks = [w / 7 for w in weeks]
        current, base = weeks[0], sum(weeks[1:]) / 4
        deviation = current / base - 1 if base else 0.0
        # The 4 week-over-week changes, newest first, the current week included: a move that
        # continues a run of 3 or more in the same direction is a trend already visible, not news.
        changes = [weeks[i] / weeks[i + 1] - 1 for i in range(4) if weeks[i + 1]]
        same_direction = sum(1 for c in changes if c != 0 and (c > 0) == (deviation > 0))
        long_trend = len(changes) == 4 and same_direction >= 3
        drift_pass = (
            bool(base) and abs(deviation) >= drift_bar and not long_trend and _floor_ok(counts, day, prior_days)
        )
        drift = _lens(
            current,
            base,
            drift_bar,
            drift_pass,
            last_7_days=round(current, 2),
            long_trend=long_trend,
            windows={
                "cur": _window(day - timedelta(days=6), day, "daily"),
                "base": _window(day - timedelta(days=34), day - timedelta(days=7), "daily"),
            },
        )
    return _combine(result, step, drift)


def _seasonal_match(series: list[tuple[date, float]], grain: str, value: float) -> bool | None:
    """Whether the same period a year earlier moved the same way, by at least half as much."""
    offset = SEASON_PERIODS.get(grain)
    if offset is None or len(series) < offset + 1:
        return None
    prev = series[-2][1]
    year_ago = series[-1 - offset][1]
    if len(series) >= offset + 2:
        year_ago_prev = series[-2 - offset][1]
        year_ago_change = year_ago / year_ago_prev - 1 if year_ago_prev else None
    else:
        # The window ends exactly at the year-ago period, so its own predecessor is out of reach:
        # read its move off the period after it, inverted, so a spike reads as a rise either way.
        year_ago_next = series[-offset][1]
        year_ago_change = year_ago / year_ago_next - 1 if year_ago_next else None
    if year_ago_change is None or not prev:
        return None
    current_change = value / prev - 1
    return (current_change > 0) == (year_ago_change > 0) and abs(year_ago_change) >= abs(current_change) / 2


def judge_period(
    grain: str, series: list[tuple[date, float]], counts: dict[date, float] | None, rate: bool = False
) -> dict:
    n_base = BASE_PERIODS[grain]
    period, value = series[-1]
    result: dict = {"grain": grain, "period": period.isoformat(), "value": value}
    base_rows = series[-1 - n_base : -1]
    base = [v for _, v in base_rows]
    if len(base) < 4 or any(b <= 0 for b in base):
        return {**result, **_insufficient(f"{len(base)} positive base periods, 4 needed")}
    base_days = [d for d, _ in base_rows]

    changes = [base[i] / base[i - 1] - 1 for i in range(1, len(base))]
    growth = _median(changes)
    swing = _median([abs(c) for c in changes])
    level = _median(base[-3:])
    expected = level * (1 + growth) ** 2
    deviation = value / expected - 1 if expected else 0.0
    bar = max(RATE_PERIOD_BAR if rate else PERIOD_BAR, STEP_SWING_FACTOR * swing)
    trend_bar = bar if rate else PERIOD_BAR
    recent = changes[-3:]
    long_trend = len(recent) == 3 and all((c >= trend_bar) if deviation > 0 else (c <= -trend_bar) for c in recent)
    step_pass = abs(deviation) >= bar and not long_trend and _floor_ok(counts, period, base_days)
    step = _lens(
        value,
        expected,
        bar,
        step_pass,
        previous=base[-1],
        level_median_of_3=round(level, 2),
        growth_per_period_pct=_pct(growth),
        swing_pct=_pct(swing),
        long_trend=long_trend,
        seasonal_match=_seasonal_match(series, grain, value),
        windows={"cur": _window(period, period, grain), "base": _window(base_days[-3], base_days[-1], grain)},
    )

    # Period drift: the last 3 periods against the 3 before, grown at the trend for 3 periods, so a
    # slow slide that never clears the step bar in one period still surfaces.
    drift_bar = max(RATE_PERIOD_DRIFT_BAR if rate else PERIOD_DRIFT_BAR, DRIFT_SWING_FACTOR * swing)
    if len(base) >= 5:
        last3_avg = (sum(base[-2:]) + value) / 3
        expected_avg = (sum(base[-5:-2]) / 3) * (1 + growth) ** 3
        drift_deviation = last3_avg / expected_avg - 1 if expected_avg else 0.0
        drift_pass = abs(drift_deviation) >= drift_bar and _floor_ok(counts, period, base_days)
        drift = _lens(
            last3_avg,
            expected_avg,
            drift_bar,
            drift_pass,
            last_3_average=round(last3_avg, 2),
            windows={
                "cur": _window(base_days[-2], period, grain),
                "base": _window(base_days[-5], base_days[-3], grain),
            },
        )
    else:
        drift = _insufficient("fewer than 6 periods for the drift lens")
    return _combine(result, step, drift)


def judge(request: dict) -> dict:
    grain = request.get("grain", "daily")
    series = _parse_series(request["series"])
    counts: dict[date, float] | None = None
    if request.get("counts"):
        counts = dict(_parse_series(request["counts"]))
    elif request.get("count_basis"):
        counts = dict(series)
    rate = bool(request.get("rate", False))
    if not series:
        result = _insufficient("no periods with a value")
    elif grain == "daily":
        result = judge_daily(series, counts, rate)
    elif grain in BASE_PERIODS:
        result = judge_period(grain, series, counts, rate)
    else:
        raise ValueError(f"unknown grain {grain!r}")
    if "name" in request:
        result = {"name": request["name"], **result}
    return result


def _driver_verdict(rows: list[dict], total: float, ratio_base: float | None = None) -> dict:
    """Driver when the top 1 or 2 segments carry 60% of the move and the rest hold.

    Relative moves are a group's delta over its own base; for a ratio the deltas are ratio
    points, so they are measured against the overall base ratio instead.
    """
    if not total or not rows:
        return {"verdict": "none", "reason": "no move to attribute"}
    top1_share = rows[0]["delta"] / total
    top = rows[:1] if top1_share >= DRIVER_SHARE or len(rows) == 1 else rows[:2]
    top_share = sum(r["delta"] for r in top) / total
    rest = rows[len(top) :]

    def relative(group: list[dict]) -> float:
        delta = sum(r["delta"] for r in group)
        base = ratio_base if ratio_base is not None else sum(r["base"] for r in group)
        return delta / base if base else 0.0

    top_relative = relative(top)
    rest_relative = relative(rest) if rest else 0.0
    rest_holds = not rest or abs(rest_relative) < abs(top_relative) / 2
    with_move = [r for r in rows if r["delta"] and (r["delta"] > 0) == (total > 0)]
    against_move = [r for r in rows if r["delta"] and (r["delta"] > 0) != (total > 0)]
    gross = sum(abs(r["delta"]) for r in rows)
    # Segments pulling both ways make shares exceed 100% and the net move understate what
    # happened, so the largest contributors on each side are named instead of a "driver".
    if against_move and abs(total) < 0.5 * gross:
        verdict = "offsetting"
    elif top_share >= DRIVER_SHARE and rest_holds:
        verdict = "driver"
    elif not against_move:
        verdict = "broad"
    else:
        verdict = "none"
    result = {
        "verdict": verdict,
        "top_segments": [r["name"] for r in top],
        "top1_share_pct": _pct(top1_share),
        "top_share_pct": _pct(top_share),
        "top_relative_move_pct": _pct(top_relative),
        "rest_relative_move_pct": _pct(rest_relative),
    }
    if verdict == "offsetting":
        result.update(
            {
                "pushing_with_the_move": [r["name"] for r in with_move[:2]],
                "pulling_against_it": [r["name"] for r in against_move[:2]],
                "gross_over_net": round(gross / abs(total), 1),
            }
        )
    return result


def _finish(kind: str, rows: list[dict], total: float, relative_base: float | None = None, **summary) -> dict:
    """Shares, ordering and the verdict, the same for a sum and a ratio."""
    scored = [r for r in rows if "delta" in r]
    scored.sort(key=lambda r: abs(r["delta"]), reverse=True)
    for r in scored:
        r["share_pct"] = _pct(r["delta"] / total) if total else None
    skipped = [r for r in rows if "delta" not in r]
    return {"kind": kind, **summary, "segments": scored + skipped, **_driver_verdict(scored, total, relative_base)}


def decompose_sum(segments: list[dict], count_basis: bool) -> dict:
    rows = []
    for seg in segments:
        cur, base = float(seg["cur"]), float(seg["base"])
        row = {"name": seg["name"], "cur": cur, "base": base, "delta": cur - base}
        row["relative_move_pct"] = _pct(row["delta"] / base) if base else None
        # The 20-unit floor is about counts: a money measure carries its own `base_count`, or no flag.
        if "base_count" in seg:
            row["small_base"] = float(seg["base_count"]) < UNIT_FLOOR
        elif count_basis:
            row["small_base"] = base < UNIT_FLOOR
        rows.append(row)
    total = sum(r["delta"] for r in rows)
    return _finish("sum", rows, total, total_delta=round(total, 2))


def decompose_ratio(segments: list[dict]) -> dict:
    den_cur_total = sum(float(s["den_cur"]) for s in segments)
    den_base_total = sum(float(s["den_base"]) for s in segments)
    ratio_cur = sum(float(s["num_cur"]) for s in segments) / den_cur_total if den_cur_total else 0.0
    ratio_base = sum(float(s["num_base"]) for s in segments) / den_base_total if den_base_total else 0.0
    total = ratio_cur - ratio_base
    rows = []
    for s in segments:
        den_cur, den_base = float(s["den_cur"]), float(s["den_base"])
        if den_cur <= 0 and den_base <= 0:
            rows.append({"name": s["name"], "skipped": "no denominator in either window"})
            continue
        w_cur, w_base = den_cur / den_cur_total, den_base / den_base_total
        # A segment absent from one window has no ratio there: the overall ratio of that window
        # stands in, which gives it a zero rate effect and leaves its mix effect, the share it
        # gained or lost, so a brand-new segment still counts toward the move.
        r_cur = float(s["num_cur"]) / den_cur if den_cur > 0 else ratio_cur
        r_base = float(s["num_base"]) / den_base if den_base > 0 else ratio_base
        mix = (w_cur - w_base) * (r_base - ratio_base)
        rate = w_cur * (r_cur - r_base)
        row = {
            "name": s["name"],
            "ratio_cur": round(r_cur, 4),
            "ratio_base": round(r_base, 4),
            "share_of_denominator_cur_pct": _pct(w_cur),
            "share_of_denominator_base_pct": _pct(w_base),
            "mix_effect": round(mix, 4),
            "rate_effect": round(rate, 4),
            "delta": mix + rate,
            "small_base": max(den_cur, den_base) < UNIT_FLOOR,
        }
        if den_base <= 0:
            row["new_segment"] = True
        if den_cur <= 0:
            row["gone_segment"] = True
        rows.append(row)
    mix_total = sum(r["mix_effect"] for r in rows if "delta" in r)
    rate_total = sum(r["rate_effect"] for r in rows if "delta" in r)
    return _finish(
        "ratio",
        rows,
        total,
        ratio_base,
        ratio_cur=round(ratio_cur, 4),
        ratio_base=round(ratio_base, 4),
        total_change=round(total, 4),
        mix_effect_total=round(mix_total, 4),
        rate_effect_total=round(rate_total, 4),
        dominant_effect="mix" if abs(mix_total) > abs(rate_total) else "rate",
    )


def decompose(request: dict) -> dict:
    kind = request.get("kind", "sum")
    if kind == "sum":
        return decompose_sum(request["segments"], bool(request.get("count_basis", False)))
    if kind == "ratio":
        return decompose_ratio(request["segments"])
    raise ValueError(f"unknown kind {kind!r}")


def concentrate(request: dict) -> dict:
    """Whether a handful of entities (customers, accounts) carry a move on a table with one row per entity.

    `entities` are the top entities by absolute delta, at most 20; `total_cur` and `total_base` are
    the whole measure in the same windows, so the entities not listed still count toward the move.
    """
    total = float(request["total_cur"]) - float(request["total_base"])
    rows = [
        {
            "name": e["name"],
            "cur": float(e["cur"]),
            "base": float(e["base"]),
            "delta": float(e["cur"]) - float(e["base"]),
        }
        for e in request["entities"]
    ]
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    if not total or not rows:
        return {"kind": "concentration", "verdict": "none", "reason": "no move to attribute"}
    for r in rows:
        r["share_pct"] = _pct(r["delta"] / total)
    with_move = [r for r in rows if r["delta"] and (r["delta"] > 0) == (total > 0)]
    top = with_move[:CONCENTRATION_ENTITIES]
    top_share = sum(r["delta"] for r in top) / total
    running, needed = 0.0, None
    for i, r in enumerate(with_move, start=1):
        running += r["delta"]
        if running / total >= DRIVER_SHARE:
            needed = i
            break
    concentrated = needed is not None and needed <= CONCENTRATION_ENTITIES
    return {
        "kind": "concentration",
        "total_delta": round(total, 2),
        "entities": rows,
        "verdict": "driver" if concentrated else "none",
        "top_entities": [r["name"] for r in with_move[:needed]] if concentrated else [],
        "entities_for_60_pct": needed,
        "top1_share_pct": _pct(with_move[0]["delta"] / total) if with_move else None,
        "top5_share_pct": _pct(top_share),
    }


def handle(request: dict) -> dict:
    mode = request.get("mode", "judge")
    if mode == "judge":
        return judge(request)
    if mode == "decompose":
        return decompose(request)
    if mode == "concentrate":
        return concentrate(request)
    raise ValueError(f"unknown mode {mode!r}")


def main() -> None:
    """One request, or `{"requests": [...]}` for many, answered in order, so a run judges every
    series in one call instead of one call per series."""
    payload = json.load(sys.stdin)
    if "requests" in payload:
        result: object = [handle(r) for r in payload["requests"]]
    else:
        result = handle(payload)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
