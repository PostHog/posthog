#!/usr/bin/env python3
"""Two-sample Kolmogorov-Smirnov change/distribution-shift detector — pure stdlib.

No numpy/scipy needed (neither is preinstalled in the scout sandbox). Reads a JSON
request on stdin and prints a JSON verdict, so the scout can pull samples via
execute-sql and pipe them straight in.

Modes (request `mode`):
  - "two_sample": compare two samples `a` and `b` (raw value lists, or binned
    [[value, count], ...] via `a_hist`/`b_hist`). Detects whether two windows'
    distributions differ — the thing point/level detectors miss.
  - "changepoint": scan an ordered `series` for the split that best separates it into
    two differently-distributed halves (KS on left vs right at each candidate point).
    This is the "where did it change" detector, not "is the latest point an outlier".

The KS statistic D = max|F_a(x) - F_b(x)|; the p-value is the asymptotic Kolmogorov
distribution with the Stephens small-sample correction (matches scipy's ks_2samp
asymptotic mode closely for n,m >~ 30).
"""

from __future__ import annotations

import sys
import json
import math


def _ks_pvalue(d: float, n: float, m: float) -> float:
    if n <= 0 or m <= 0 or d <= 0:
        return 1.0
    en = math.sqrt(n * m / (n + m))
    t = (en + 0.12 + 0.11 / en) * d  # Stephens correction
    if t < 1e-12:
        return 1.0
    s = 0.0
    for k in range(1, 101):
        term = 2.0 * (-1) ** (k - 1) * math.exp(-2.0 * k * k * t * t)
        s += term
        if abs(term) < 1e-10:
            break
    return max(0.0, min(1.0, s))


def ks_2samp(a: list[float], b: list[float]) -> tuple[float, float]:
    a = sorted(a)
    b = sorted(b)
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return 0.0, 1.0
    i = j = 0
    d = 0.0
    while i < n and j < m:
        x = a[i] if a[i] <= b[j] else b[j]
        while i < n and a[i] <= x:
            i += 1
        while j < m and b[j] <= x:
            j += 1
        d = max(d, abs(i / n - j / m))
    return d, _ks_pvalue(d, n, m)


def ks_2samp_binned(a_hist: list[list[float]], b_hist: list[list[float]]) -> tuple[float, float]:
    """KS on two empirical CDFs given as (value, count) bins — the cheap-payload path."""
    ca: dict[float, float] = {}
    cb: dict[float, float] = {}
    for v, c in a_hist:
        ca[v] = ca.get(v, 0.0) + c
    for v, c in b_hist:
        cb[v] = cb.get(v, 0.0) + c
    na = sum(ca.values())
    nb = sum(cb.values())
    if na == 0 or nb == 0:
        return 0.0, 1.0
    fa = fb = d = 0.0
    for v in sorted(set(ca) | set(cb)):
        fa += ca.get(v, 0.0) / na
        fb += cb.get(v, 0.0) / nb
        d = max(d, abs(fa - fb))
    return d, _ks_pvalue(d, na, nb)


def changepoint(series: list[float], min_seg: int = 8) -> dict:
    """Find the split index whose left/right value distributions differ most (max D).

    The sweep picks the split that maximizes D over many candidates, so the winning
    `p` is a **scan minimum** — biased low by multiple comparisons and NOT a
    single-hypothesis p-value. Use `p_adj` (Bonferroni over `tests`) as the calibrated
    figure, and confirm the chosen split with a direct two-sample KS on
    seasonality-matched windows before treating it as emit evidence.
    """
    n = len(series)
    if n < 2 * min_seg:
        return {"changepoint": None, "reason": f"need >= {2 * min_seg} points, got {n}"}
    best = {"index": None, "d": 0.0, "p": 1.0}
    tests = 0
    for c in range(min_seg, n - min_seg + 1):
        tests += 1
        d, p = ks_2samp(series[:c], series[c:])
        if d > best["d"]:
            best = {"index": c, "d": d, "p": p}
    return {
        "changepoint": best["index"],
        "d": round(best["d"], 4),
        "p": best["p"],  # scan minimum — uncorrected; see p_adj
        "p_adj": min(1.0, best["p"] * tests),  # Bonferroni over the scan
        "tests": tests,
        "n": n,
    }


def main() -> None:
    req = json.load(sys.stdin)
    mode = req.get("mode", "two_sample")
    if mode == "changepoint":
        out = changepoint(req["series"], min_seg=req.get("min_seg", 8))
    elif "a_hist" in req or "b_hist" in req:
        if "a_hist" not in req or "b_hist" not in req:
            out = {"error": "binned mode needs both a_hist and b_hist"}
        else:
            d, p = ks_2samp_binned(req["a_hist"], req["b_hist"])
            out = {"d": round(d, 4), "p": p, "na": sum(c for _, c in req["a_hist"]), "nb": sum(c for _, c in req["b_hist"])}
    else:
        d, p = ks_2samp(req["a"], req["b"])
        out = {"d": round(d, 4), "p": p, "n": len(req["a"]), "m": len(req["b"])}
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
