#!/usr/bin/env python3
"""Run one candidate query, capture artifacts, compare to baseline."""

from __future__ import annotations

import sys
import json
import argparse
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    AdapterConfig,
    AutoresearchError,
    emit_metrics_from_json,
    execute_query,
    info,
    next_run_id,
    require_file,
    write_last_run_json,
)

SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--label", default="")
    return parser.parse_args(argv)


def _write_failure_metrics(metrics_file: Path, note: str) -> None:
    metrics_file.parent.mkdir(parents=True, exist_ok=True)
    metrics_file.write_text(
        json.dumps(
            {
                "primary": {"name": "latency_ms", "value": -1, "unit": "ms"},
                "secondary": {},
                "notes": note,
            },
            indent=2,
        )
        + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    workspace: Path = args.workspace
    candidate_file = workspace / "query" / "current.sql"
    baseline_result = workspace / "baseline" / "result.tsv"
    require_file(candidate_file)
    require_file(baseline_result)

    run_id = next_run_id(workspace)
    run_name = f"{run_id}-{args.label}" if args.label else run_id
    run_dir = workspace / "runs" / run_name
    profile_dir = run_dir / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    result_file = run_dir / "result.tsv"
    metrics_file = run_dir / "metrics.json"
    stdout_file = run_dir / "stdout.log"
    comparison_file = run_dir / "comparison.json"
    last_run = workspace / "runtime" / "last_run.json"
    last_run.parent.mkdir(parents=True, exist_ok=True)

    adapter = AdapterConfig.load(workspace)
    transport = adapter.transport()

    info(f"running candidate ({run_name}): {candidate_file}")
    try:
        execute_query(
            transport,
            candidate_file,
            result_file=result_file,
            metrics_file=metrics_file,
            stdout_file=stdout_file,
        )
    except AutoresearchError as err:
        info(f"candidate query failed: {err}")
        _write_failure_metrics(metrics_file, str(err))
        write_last_run_json(
            last_run,
            kind="candidate",
            run_id=run_id,
            label=args.label,
            run_dir=run_dir,
            result_file="",
            metrics_file=metrics_file,
            comparison_file="",
        )
        print("METRIC latency_ms=-1")
        return 0

    # Exit 0 = match, 1 = mismatch, 2 = comparator crashed. Both 0 and 1
    # leave a definitive comparison.json behind for the agent to reason
    # about. Exit 2 does NOT — on crash we write an error-shaped
    # comparison.json ourselves so the skill can't mistake "failed to
    # verify" for "matches baseline."
    compare_result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(SCRIPT_DIR / "ch_compare_results.py"),
            "--workspace",
            str(workspace),
            "--candidate-result",
            str(result_file),
            "--output",
            str(comparison_file),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if compare_result.returncode not in (0, 1):
        err_detail = (compare_result.stderr or "").strip()[:500]
        info(f"comparison crashed (exit {compare_result.returncode}): {err_detail}")
        comparison_file.parent.mkdir(parents=True, exist_ok=True)
        comparison_file.write_text(
            json.dumps(
                {
                    "matches": False,
                    "mode": "sorted-line",
                    "summary": f"comparator crashed (exit {compare_result.returncode})",
                    "error": err_detail,
                },
                indent=2,
            )
            + "\n"
        )
        # Overwrite metrics.json with a failure marker and emit METRIC
        # latency_ms=-1 (matching the execute-failure branch above) so
        # pi-autoresearch's lane-stagnation heuristic treats a lane full of
        # crashed comparators the same as one full of failed executes, not
        # like one that produced nothing. Harvest filters on `value < 0` and
        # `comparison.matches == True`, so this sentinel won't crown the run.
        _write_failure_metrics(metrics_file, f"comparator crashed (exit {compare_result.returncode})")
        write_last_run_json(
            last_run,
            kind="candidate",
            run_id=run_id,
            label=args.label,
            run_dir=run_dir,
            result_file=result_file,
            metrics_file=metrics_file,
            comparison_file=comparison_file,
        )
        print("METRIC latency_ms=-1")
        return 0

    write_last_run_json(
        last_run,
        kind="candidate",
        run_id=run_id,
        label=args.label,
        run_dir=run_dir,
        result_file=result_file,
        metrics_file=metrics_file,
        comparison_file=comparison_file,
    )

    emit_metrics_from_json(metrics_file)

    rows = len(result_file.read_text().splitlines())
    info(f"candidate {run_name} captured: {rows} result rows")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AutoresearchError as err:
        print(f"error: {err}", file=sys.stderr)
        sys.exit(1)
