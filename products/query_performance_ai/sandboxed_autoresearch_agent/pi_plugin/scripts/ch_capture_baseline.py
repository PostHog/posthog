#!/usr/bin/env python3
"""Capture a baseline run via the workspace's configured transport."""

from __future__ import annotations

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    AdapterConfig,
    AutoresearchError,
    emit_metrics_from_json,
    execute_query,
    info,
    require_file,
    write_last_run_json,
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    workspace: Path = args.workspace
    query_file = workspace / "query" / "original.sql"
    baseline_dir = workspace / "baseline"
    result_file = baseline_dir / "result.jsonl"
    metrics_file = baseline_dir / "metrics.json"
    stdout_file = baseline_dir / "stdout.log"
    profile_dir = baseline_dir / "profile"
    last_run = workspace / "runtime" / "last_run.json"

    require_file(query_file)
    profile_dir.mkdir(parents=True, exist_ok=True)
    last_run.parent.mkdir(parents=True, exist_ok=True)

    adapter = AdapterConfig.load(workspace)
    transport = adapter.transport()

    info(f"running baseline: {query_file}")
    execute_query(
        transport,
        query_file,
        result_file=result_file,
        metrics_file=metrics_file,
        stdout_file=stdout_file,
    )

    write_last_run_json(
        last_run,
        kind="baseline",
        run_id="baseline",
        label="",
        run_dir=baseline_dir,
        result_file=result_file,
        metrics_file=metrics_file,
        comparison_file="",
    )

    emit_metrics_from_json(metrics_file)

    rows = len(result_file.read_text().splitlines())
    info(f"baseline captured: {rows} result rows, metrics in {metrics_file}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AutoresearchError as err:
        print(f"error: {err}", file=sys.stderr)
        sys.exit(1)
