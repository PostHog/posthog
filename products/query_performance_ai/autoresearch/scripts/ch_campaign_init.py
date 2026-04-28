#!/usr/bin/env python3
"""Initialize a new autoresearch campaign workspace.

Port of the former ``ch_campaign_init.sh``. Creates the workspace directory
layout, renders campaign metadata and the wrapper scripts, and seeds the
query files if a source SQL file is provided.
"""

from __future__ import annotations

import sys
import json
import shutil
import argparse
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import AutoresearchError, info  # noqa: E402

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def _current_branch() -> str:
    try:
        result = subprocess.run(  # noqa: S603 — fixed argv
            ["git", "branch", "--show-current"],
            check=False,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _render_file(path: Path, values: dict[str, str]) -> None:
    """Replace ``__KEY__`` tokens with values in-place."""
    content = path.read_text()
    for key, value in values.items():
        content = content.replace(f"__{key}__", value)
    path.write_text(content)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--query-id", required=True)
    parser.add_argument("--query-file", type=Path)
    parser.add_argument("--primary-metric", default="latency_ms")
    parser.add_argument("--metric-unit", default="ms")
    parser.add_argument("--direction", choices=("lower", "higher"), default="lower")
    parser.add_argument("--branch-name")
    parser.add_argument("--lane-stagnation-window", type=int, default=4)
    parser.add_argument("--campaign-stagnation-window", type=int, default=8)
    parser.add_argument("--max-total-iterations", type=int, default=30)
    parser.add_argument("--significant-improvement-pct", type=float, default=3)
    parser.add_argument("--repair-budget", type=int, default=2)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    branch = args.branch_name or _current_branch()
    if not branch:
        raise AutoresearchError("could not determine git branch; pass --branch-name")

    workspace: Path = args.workspace
    if workspace.exists() and any(workspace.iterdir()):
        raise AutoresearchError(f"workspace already exists and is not empty: {workspace}")

    workspace.mkdir(parents=True, exist_ok=True)
    template_root = PACKAGE_ROOT / "templates" / "workspace"
    for child in template_root.iterdir():
        dest = workspace / child.name
        if child.is_dir():
            shutil.copytree(child, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(child, dest)

    # Rename example files so users see writable ``adapter.json`` /
    # ``campaign.json``. The ``.example`` extension on the templates keeps
    # them off oxfmt's JSON-syntax check while they still hold ``__KEY__``
    # placeholders.
    for example_name, target_name in (
        ("adapter.json.example", "adapter.json"),
        ("campaign.json.example", "campaign.json"),
    ):
        example_path = workspace / example_name
        target_path = workspace / target_name
        if example_path.is_file() and not target_path.is_file():
            example_path.rename(target_path)

    values = {
        "QUERY_ID": args.query_id,
        "BRANCH_NAME": branch,
        "PRIMARY_METRIC": args.primary_metric,
        "METRIC_UNIT": args.metric_unit,
        "DIRECTION": args.direction,
        "SIGNIFICANT_IMPROVEMENT_PCT": str(args.significant_improvement_pct),
        "LANE_STAGNATION_WINDOW": str(args.lane_stagnation_window),
        "CAMPAIGN_STAGNATION_WINDOW": str(args.campaign_stagnation_window),
        "MAX_TOTAL_ITERATIONS": str(args.max_total_iterations),
        "REPAIR_BUDGET": str(args.repair_budget),
        "PACKAGE_ROOT": str(PACKAGE_ROOT),
        "WORKSPACE_ROOT": str(workspace),
        "WORKSPACE_RUNTIME": "./",
    }
    for name in ("campaign.json", "autoresearch.md", "autoresearch.py", "autoresearch_checks.py"):
        target = workspace / name
        if target.is_file():
            _render_file(target, values)

    for name in ("autoresearch.py", "autoresearch_checks.py"):
        target = workspace / name
        if target.is_file():
            target.chmod(0o755)

    if args.query_file is not None:
        src = args.query_file
        if not src.is_file():
            raise AutoresearchError(f"--query-file does not exist: {src}")
        for dst_name in ("original.sql", "current.sql", "best.sql"):
            shutil.copy2(src, workspace / "query" / dst_name)

    # pi-autoresearch expects autoresearch.config.json in the directory it
    # runs from — which in the reference setup is the parent of the workspace.
    # Writing it alongside the workspace keeps that layout and avoids
    # polluting the caller's cwd.
    config_path = workspace.parent / "autoresearch.config.json"
    if not config_path.exists():
        config_path.write_text(
            json.dumps(
                {"workingDir": str(workspace), "maxIterations": args.max_total_iterations},
                indent=2,
            )
            + "\n"
        )
    else:
        info(f"left existing {config_path} untouched")

    print(
        f"""\
Initialized ClickHouse autoresearch workspace.
- workspace: {workspace}
- query_id: {args.query_id}
- branch: {branch}
- package_root: {PACKAGE_ROOT}

Next steps:
1. Fill in {workspace / "adapter.json"}
2. Capture the baseline:
   python3 {PACKAGE_ROOT / "scripts" / "ch_capture_baseline.py"} --workspace {workspace}
"""
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AutoresearchError as err:
        print(f"error: {err}", file=sys.stderr)
        sys.exit(1)
