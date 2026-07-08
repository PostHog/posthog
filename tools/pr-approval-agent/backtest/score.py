#!/usr/bin/env python3
# ruff: noqa: T201
"""Score replay results against outcome labels and the as-run verdicts.

Reads every data/results/<cohort>_<arm>_rep<k>/ directory, aggregates reps per
trace by modal verdict, joins data/labels.jsonl, and prints per-(cohort, arm):

  approval%        share of scored traces with modal verdict APPROVE
  false-refusal%   non-APPROVE modal verdict on a PR that later merged unchanged
  agree-asrun%     modal verdict == the original production verdict
  flip-rate%       traces whose verdict varies across reps (needs >=2 reps)

Then lists verdict flips vs production (PR, original -> replayed) for spot reads.
"""

from __future__ import annotations

import json
from collections import defaultdict

from backtest_lib import RUN_DIR_RE, data_dir, modal_verdict, pct


def load_labels() -> dict[str, dict]:
    labels = {}
    for line in (data_dir() / "labels.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row.get("trace_id"):
            labels[row["trace_id"]] = row
    return labels


def load_runs() -> dict[tuple[str, str], dict[str, list[dict]]]:
    """(cohort, arm) -> trace_id -> [rep results]."""
    results_dir = data_dir() / "results"
    runs: dict[tuple[str, str], dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for run_dir in sorted(results_dir.iterdir()) if results_dir.exists() else []:
        match = RUN_DIR_RE.match(run_dir.name)
        if not match:
            continue
        key = (match["cohort"], match["arm"])
        for path in run_dir.glob("*.json"):
            result = json.loads(path.read_text())
            if result.get("verdict"):
                runs[key][result["trace_id"]].append(result)
    return runs


def main() -> None:
    labels = load_labels()
    runs = load_runs()
    if not runs:
        raise SystemExit("no results yet — run replay.py first")

    print(f"{'cohort':<10}{'arm':<12}{'n':>4} {'approve':>8} {'false-ref':>10} {'agree-asrun':>12} {'flip':>6}")
    flips: dict[tuple[str, str], list[str]] = {}
    for (cohort, arm), traces in sorted(runs.items()):
        n = approvals = false_refusals = unchanged_n = agree = agree_n = flip = multi = 0
        arm_flips: list[str] = []
        for trace_id, results in traces.items():
            verdict = modal_verdict(results)
            n += 1
            if verdict == "APPROVE":
                approvals += 1
            label = labels.get(trace_id, {})
            if label.get("merged_unchanged"):
                unchanged_n += 1
                if verdict != "APPROVE":
                    false_refusals += 1
            original = results[0].get("original_verdict")
            if original:
                agree_n += 1
                if verdict == original:
                    agree += 1
                else:
                    arm_flips.append(f"    PR {results[0]['pr']}: {original} -> {verdict}")
            if len(results) >= 2:
                multi += 1
                if len({r["verdict"]["verdict"] for r in results}) > 1:
                    flip += 1
        flips[(cohort, arm)] = arm_flips
        print(
            f"{cohort:<10}{arm:<12}{n:>4} {pct(approvals, n):>8} {pct(false_refusals, unchanged_n):>10}"
            f" {pct(agree, agree_n):>12} {pct(flip, multi):>6}"
        )

    for (cohort, arm), arm_flips in flips.items():
        if arm_flips:
            print(f"\nflips vs production — cohort {cohort}, arm {arm}:")
            print("\n".join(sorted(arm_flips)))


if __name__ == "__main__":
    main()
