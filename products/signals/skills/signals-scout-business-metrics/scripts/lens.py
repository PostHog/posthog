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
    The 20-unit floor applies to counts only: set `count_basis` when the series itself is a
    count, or pass `counts`, a parallel count series, when the measure is money or a ratio.
    With neither, no floor applies.
    Daily runs the step lens (latest day vs the 28-day median and the same-weekday median) and
    the drift lens (last 7 days vs the 4 prior weeks). Weekly, monthly and quarterly run the
    period lens (latest closed period vs its trend expectation, under a volatility-aware bar)
    and a period drift lens (the last 3 periods vs the 3 before, trend-adjusted).
  - "decompose": attribute a move to segments.
      {"mode": "decompose", "kind": "sum",
       "segments": [{"name": "pro", "cur": 120, "base": 100}, ...]}
      {"mode": "decompose", "kind": "ratio",
       "segments": [{"name": "pro", "num_cur": 12, "den_cur": 100,
                     "num_base": 10, "den_base": 90}, ...]}
    `cur` is the current window, `base` the average base period. For a ratio the mix effect is
    the segment's share of the denominator changing, the rate effect its own ratio changing.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta

STEP_BAR = 0.30
DRIFT_BAR = 0.15
PERIOD_BAR = 0.20
PERIOD_DRIFT_BAR = 0.10
BROAD_FACTOR = 1.5
UNIT_FLOOR = 20
BASE_PERIODS = {"weekly": 8, "monthly": 6, "quarterly": 4}
SEASON_PERIODS = {"weekly": 52, "monthly": 12, "quarterly": 4}
DRIVER_SHARE = 0.60


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        raise ValueError("median of nothing")
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _pct(value: float) -> float:
    return round(value * 100, 1)


def _parse_series(rows: list) -> list[tuple[date, float]]:
    parsed = [(date.fromisoformat(str(day)[:10]), float(value)) for day, value in rows]
    parsed.sort(key=lambda pair: pair[0])
    return parsed


def _floor_ok(value: float, reference: float, counts: dict[date, float] | None, day: date, count_basis: bool) -> bool:
    """The 20-unit floor on the count behind a move; no floor for a money or ratio series without counts."""
    if counts:
        count_value = counts.get(day, 0.0)
        count_reference = _median(list(counts.values()))
        return max(count_value, count_reference) >= UNIT_FLOOR
    if count_basis:
        return max(value, reference) >= UNIT_FLOOR
    return True


def judge_daily(series: list[tuple[date, float]], counts: dict[date, float] | None, count_basis: bool) -> dict:
    by_day = dict(series)
    day, value = series[-1]
    prior = [v for d, v in series if day - timedelta(days=28) <= d < day]
    result: dict = {"grain": "daily", "period": day.isoformat(), "value": value}
    if len(prior) < 14:
        result["verdict"] = "insufficient history"
        result["reason"] = f"{len(prior)} prior days, 14 needed"
        return result
    median_28d = _median(prior)
    same_weekday = [by_day[day - timedelta(days=7 * k)] for k in (1, 2, 3, 4) if day - timedelta(days=7 * k) in by_day]
    median_same_weekday = _median(same_weekday) if len(same_weekday) >= 3 else median_28d
    step = {
        "median_28d": round(median_28d, 2),
        "median_same_weekday": round(median_same_weekday, 2),
        "deviation_from_28d_pct": _pct(value / median_28d - 1) if median_28d else None,
        "deviation_from_same_weekday_pct": _pct(value / median_same_weekday - 1) if median_same_weekday else None,
        "bar_pct": _pct(STEP_BAR),
    }
    step_pass = (
        median_28d > 0
        and median_same_weekday > 0
        and abs(value - median_28d) >= STEP_BAR * median_28d
        and abs(value - median_same_weekday) >= STEP_BAR * median_same_weekday
        and _floor_ok(value, median_28d, counts, day, count_basis)
    )
    step["verdict"] = "move" if step_pass else "within"

    weeks = []
    for k in range(5):
        end = day - timedelta(days=7 * k)
        start = end - timedelta(days=6)
        days = [by_day[d] for d in (start + timedelta(days=i) for i in range(7)) if d in by_day]
        weeks.append(sum(days) if len(days) == 7 else None)
    drift: dict = {"bar_pct": _pct(DRIFT_BAR)}
    if any(w is None for w in weeks):
        drift["verdict"] = "insufficient history"
    else:
        current, prior_weeks = weeks[0], weeks[1:]
        base = sum(prior_weeks) / 4
        deviation = current / base - 1 if base else 0.0
        changes = [prior_weeks[i] / prior_weeks[i + 1] - 1 for i in range(3) if prior_weeks[i + 1]]
        same_direction = sum(1 for c in changes if (c > 0) == (deviation > 0) and c != 0)
        long_trend = len(changes) == 3 and same_direction == 3
        drift.update(
            {
                "last_7_days": round(current, 2),
                "prior_4_weeks_average": round(base, 2),
                "deviation_pct": _pct(deviation),
                "long_trend": long_trend,
                "verdict": "move" if abs(deviation) >= DRIFT_BAR and not long_trend and base else "within",
            }
        )
    result["step"] = step
    result["drift"] = drift
    result["verdict"] = "move" if step["verdict"] == "move" or drift.get("verdict") == "move" else "within"
    return result


def judge_period(grain: str, series: list[tuple[date, float]], counts: dict[date, float] | None, count_basis: bool) -> dict:
    n_base = BASE_PERIODS[grain]
    period, value = series[-1]
    base = [v for _, v in series[-1 - n_base : -1]]
    result: dict = {"grain": grain, "period": period.isoformat(), "value": value}
    if len(base) < 4 or any(b <= 0 for b in base):
        result["verdict"] = "insufficient history"
        result["reason"] = f"{len(base)} positive base periods, 4 needed"
        return result
    changes = [base[i] / base[i - 1] - 1 for i in range(1, len(base))]
    growth = _median(changes)
    swing = _median([abs(c) for c in changes])
    level = _median(base[-3:])
    expected = level * (1 + growth) ** 2
    deviation = value / expected - 1 if expected else 0.0
    bar = max(PERIOD_BAR, 2 * swing)
    recent = changes[-3:]
    long_trend = len(recent) == 3 and all((c >= PERIOD_BAR) if deviation > 0 else (c <= -PERIOD_BAR) for c in recent)
    seasonal_match = None
    offset = SEASON_PERIODS[grain]
    if len(series) >= offset + 2:
        year_ago = series[-1 - offset][1]
        year_ago_prev = series[-2 - offset][1]
        prev = series[-2][1]
        if year_ago_prev and prev:
            current_change = value / prev - 1
            year_ago_change = year_ago / year_ago_prev - 1
            seasonal_match = (current_change > 0) == (year_ago_change > 0) and abs(year_ago_change) >= abs(current_change) / 2
    step_pass = abs(deviation) >= bar and _floor_ok(value, expected, counts, period, count_basis) and not long_trend
    result.update(
        {
            "previous": base[-1],
            "level_median_of_3": round(level, 2),
            "growth_per_period_pct": _pct(growth),
            "expected": round(expected, 2),
            "deviation_pct": _pct(deviation),
            "swing_pct": _pct(swing),
            "bar_pct": _pct(bar),
            "report_bar_pct": _pct(bar * BROAD_FACTOR),
            "clears_report_bar": abs(deviation) >= bar * BROAD_FACTOR,
            "long_trend": long_trend,
            "seasonal_match": seasonal_match,
            "step_verdict": "move" if step_pass else "within",
        }
    )

    # Period drift: the last 3 periods against the 3 before, grown at the trend for 3 periods, so a
    # slow slide that never clears the step bar in one period still surfaces.
    drift_bar = max(PERIOD_DRIFT_BAR, 1.5 * swing)
    drift: dict = {"bar_pct": _pct(drift_bar)}
    if len(base) >= 5:
        last3 = base[-2:] + [value]
        prior3 = base[-5:-2]
        prior_avg = sum(prior3) / 3
        expected_avg = prior_avg * (1 + growth) ** 3
        drift_deviation = (sum(last3) / 3) / expected_avg - 1 if expected_avg else 0.0
        drift_pass = abs(drift_deviation) >= drift_bar and _floor_ok(sum(last3) / 3, expected_avg, counts, period, count_basis)
        drift.update(
            {
                "last_3_average": round(sum(last3) / 3, 2),
                "prior_3_average": round(prior_avg, 2),
                "expected_average": round(expected_avg, 2),
                "deviation_pct": _pct(drift_deviation),
                "report_bar_pct": _pct(drift_bar * BROAD_FACTOR),
                "clears_report_bar": abs(drift_deviation) >= drift_bar * BROAD_FACTOR,
                "verdict": "move" if drift_pass else "within",
            }
        )
    else:
        drift["verdict"] = "insufficient history"
    result["drift"] = drift
    result["verdict"] = "move" if step_pass or drift.get("verdict") == "move" else "within"
    return result


def judge(request: dict) -> dict:
    grain = request.get("grain", "daily")
    series = _parse_series(request["series"])
    counts = dict(_parse_series(request["counts"])) if request.get("counts") else None
    count_basis = bool(request.get("count_basis", False))
    if len(series) < 2:
        return {"verdict": "insufficient history", "reason": "fewer than 2 periods"}
    if grain == "daily":
        return judge_daily(series, counts, count_basis)
    if grain in BASE_PERIODS:
        return judge_period(grain, series, counts, count_basis)
    raise ValueError(f"unknown grain {grain!r}")


def decompose_sum(segments: list[dict]) -> dict:
    rows = []
    for seg in segments:
        cur, base = float(seg["cur"]), float(seg["base"])
        rows.append({"name": seg["name"], "cur": cur, "base": base, "delta": cur - base})
    total = sum(r["delta"] for r in rows)
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    for r in rows:
        r["share_pct"] = _pct(r["delta"] / total) if total else None
        r["relative_move_pct"] = _pct(r["delta"] / r["base"]) if r["base"] else None
        r["small_base"] = r["base"] < UNIT_FLOOR
    return {"kind": "sum", "total_delta": round(total, 2), "segments": rows, **_driver_verdict(rows, total)}


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
    same_sign = all((r["delta"] > 0) == (total > 0) for r in rows if r["delta"])
    if top_share >= DRIVER_SHARE and rest_holds:
        verdict = "driver"
    elif same_sign:
        verdict = "broad"
    else:
        verdict = "none"
    return {
        "verdict": verdict,
        "top_segments": [r["name"] for r in top],
        "top1_share_pct": _pct(top1_share),
        "top_share_pct": _pct(top_share),
        "top_relative_move_pct": _pct(top_relative),
        "rest_relative_move_pct": _pct(rest_relative),
    }


def decompose_ratio(segments: list[dict]) -> dict:
    den_cur_total = sum(float(s["den_cur"]) for s in segments)
    den_base_total = sum(float(s["den_base"]) for s in segments)
    num_cur_total = sum(float(s["num_cur"]) for s in segments)
    num_base_total = sum(float(s["num_base"]) for s in segments)
    ratio_cur = num_cur_total / den_cur_total if den_cur_total else 0.0
    ratio_base = num_base_total / den_base_total if den_base_total else 0.0
    total = ratio_cur - ratio_base
    rows = []
    for s in segments:
        den_cur, den_base = float(s["den_cur"]), float(s["den_base"])
        if den_cur <= 0 or den_base <= 0:
            rows.append({"name": s["name"], "skipped": "zero denominator in a window"})
            continue
        w_cur, w_base = den_cur / den_cur_total, den_base / den_base_total
        r_cur, r_base = float(s["num_cur"]) / den_cur, float(s["num_base"]) / den_base
        mix = (w_cur - w_base) * r_base
        rate = w_cur * (r_cur - r_base)
        rows.append(
            {
                "name": s["name"],
                "ratio_cur": round(r_cur, 4),
                "ratio_base": round(r_base, 4),
                "share_of_denominator_cur_pct": _pct(w_cur),
                "share_of_denominator_base_pct": _pct(w_base),
                "mix_effect": round(mix, 4),
                "rate_effect": round(rate, 4),
                "delta": mix + rate,
                "base": den_base,
                "share_pct": _pct((mix + rate) / total) if total else None,
                "small_base": den_base < UNIT_FLOOR,
            }
        )
    scored = [r for r in rows if "delta" in r]
    scored.sort(key=lambda r: abs(r["delta"]), reverse=True)
    mix_total = sum(r["mix_effect"] for r in scored)
    rate_total = sum(r["rate_effect"] for r in scored)
    return {
        "kind": "ratio",
        "ratio_cur": round(ratio_cur, 4),
        "ratio_base": round(ratio_base, 4),
        "total_change": round(total, 4),
        "mix_effect_total": round(mix_total, 4),
        "rate_effect_total": round(rate_total, 4),
        "dominant_effect": "mix" if abs(mix_total) > abs(rate_total) else "rate",
        "segments": rows,
        **_driver_verdict(scored, total, ratio_base=ratio_base),
    }


def decompose(request: dict) -> dict:
    kind = request.get("kind", "sum")
    if kind == "sum":
        return decompose_sum(request["segments"])
    if kind == "ratio":
        return decompose_ratio(request["segments"])
    raise ValueError(f"unknown kind {kind!r}")


def main() -> None:
    request = json.load(sys.stdin)
    mode = request.get("mode", "judge")
    if mode == "judge":
        result = judge(request)
    elif mode == "decompose":
        result = decompose(request)
    else:
        raise ValueError(f"unknown mode {mode!r}")
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
