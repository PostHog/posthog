#!/usr/bin/env python3
"""Workspace-local correctness check invoked by pi-autoresearch.

Reads ``runtime/last_run.json`` -> ``comparison.json``. Exits 0 on match,
1 on mismatch, 2 on missing artifacts.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent


def main() -> int:
    last_run_path = WORKSPACE_DIR / "runtime" / "last_run.json"
    if not last_run_path.is_file():
        print(f"checks failed: missing {last_run_path}", file=sys.stderr)
        return 2

    last_run = json.loads(last_run_path.read_text())
    comparison_file = last_run.get("comparison_file") or ""
    if not comparison_file or not Path(comparison_file).is_file():
        print("checks failed: missing comparison file", file=sys.stderr)
        return 2

    comparison = json.loads(Path(comparison_file).read_text())
    summary = comparison.get("summary") or "comparison failed"
    if comparison.get("matches"):
        print(f"checks passed: {summary}")
        return 0

    print(f"checks failed: {summary}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
