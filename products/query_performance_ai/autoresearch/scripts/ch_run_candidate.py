#!/usr/bin/env python3
"""Run one candidate query, capture artifacts, compare to baseline."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
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

    # Best effort — mismatch is acceptable, the agent decides next.
    subprocess.run(  # noqa: S603
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
    )

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
