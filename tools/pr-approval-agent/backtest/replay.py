#!/usr/bin/env python3
# ruff: noqa: T201
# /// script
# requires-python = ">=3.11"
# dependencies = ["claude-agent-sdk", "anthropic", "pyyaml"]
# ///
"""Replay captured stamphog reviews under a candidate system prompt.

Arms:
  asrun    stored system prompt (from the trace) — reproducibility control
  current  REVIEWER_SYSTEM composed from this working tree — the candidate
  a path:  arbitrary system prompt file

The stored user prompt references a diff file inside the production checkout;
each run rewrites that path and materializes the diff from data/diffs/ (see
prep_prs.py). Results land in data/results/<cohort>_<arm>_rep<k>/ (resumable).

Deliberately does NOT emit PostHog traces (plain SDK query, gateway env
stripped), so backtest runs never pollute production stamphog analytics.

Usage:
  ANTHROPIC_API_KEY=... uv run replay.py --cohort 2.0.0b1 --arm current [--rep 1] [--limit 10]
"""

from __future__ import annotations

import os
import sys
import json
import asyncio
import argparse
from pathlib import Path

from backtest_lib import data_dir, load_manifest, rewrite_diff_path, split_trace_input

CONCURRENCY = 4


def load_reviewer_module():
    """Import the repo's reviewer module so schema, validation, and model stay canonical."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    # Force the untraced direct-Anthropic path: no gateway, no PostHog emission.
    for var in ("AI_GATEWAY_URL", "AI_GATEWAY_API_KEY", "POSTHOG_API_KEY"):
        os.environ.pop(var, None)
    import reviewer  # noqa: PLC0415 — path only exists after the insert above

    return reviewer


def arm_system_prompt(arm: str, stored_system: str, reviewer_module) -> str:
    if arm == "asrun":
        if stored_system:
            return stored_system
        # Gateway-era traces store no system message; reuse one captured from a
        # traced-path run of the same version (byte-identical by construction).
        fallback = data_dir() / "systems" / "asrun_fallback.txt"
        if fallback.exists():
            return fallback.read_text()
        raise ValueError("trace has no stored system prompt and data/systems/asrun_fallback.txt is missing")
    if arm == "current":
        return reviewer_module.REVIEWER_SYSTEM
    return Path(arm).read_text()


async def replay_one(
    row: dict, arm: str, rep: int, repo: Path, reviewer_module, semaphore: asyncio.Semaphore, out_dir: Path
) -> str:
    from claude_agent_sdk import (  # noqa: PLC0415 — dep resolved by uv at run time
        ClaudeAgentOptions,
        ResultMessage,
        query,
    )

    trace_id = row["trace_id"]
    out_path = out_dir / f"{trace_id}.json"
    if out_path.exists():
        return "cached"

    trace_path = data_dir() / "traces" / f"{trace_id}.json"
    diff_src = data_dir() / "diffs" / f"{int(row['pr'])}.patch"
    if not trace_path.exists():
        return "no-trace"
    if not diff_src.exists():
        return "no-diff"

    stored_system, user_prompt = split_trace_input(trace_path)
    diff_dst = repo / f".pr-review-diff-{trace_id[:8]}.patch"
    diff_dst.write_text(diff_src.read_text())
    user_prompt = rewrite_diff_path(user_prompt, diff_dst)

    quick = row.get("t1_subclass") == "T1a-trivial" or row.get("gate_verdict") == "DENIED"
    options = ClaudeAgentOptions(
        system_prompt=arm_system_prompt(arm, stored_system, reviewer_module),
        allowed_tools=["Read", "Grep", "Glob"],
        disallowed_tools=["Write", "Edit", "NotebookEdit", "Bash", "Agent", "WebFetch", "WebSearch"],
        cwd=str(repo),
        max_turns=5 if quick else 20,
        model=reviewer_module.MODEL,
        permission_mode="dontAsk",
        output_format=reviewer_module.VERDICT_SCHEMA,
        effort="low" if quick else "high",
        extra_args={"no-session-persistence": None},
    )

    async with semaphore:
        structured = None
        error = None
        try:
            async for message in query(prompt=user_prompt, options=options):
                if isinstance(message, ResultMessage) and message.structured_output:
                    structured = message.structured_output
        except Exception as exc:  # keep the sweep going; the row records the failure
            error = f"{type(exc).__name__}: {exc}"
        finally:
            diff_dst.unlink(missing_ok=True)

    result = {
        "trace_id": trace_id,
        "pr": int(row["pr"]),
        "cohort": row["cohort"],
        "arm": arm,
        "rep": rep,
        "original_verdict": row.get("llm_verdict"),
        "verdict": (reviewer_module._validate_verdict(structured) if structured else None),
        "error": error,
    }
    out_path.write_text(json.dumps(result, indent=1))
    return "error" if error else "done"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[2], help="pinned checkout for tools and diffs"
    )
    parser.add_argument("--cohort", required=True, help="stamphog_version value, or 'unmarked'")
    parser.add_argument("--arm", required=True, help="asrun | current | path to a system prompt file")
    parser.add_argument("--rep", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--all-gates", action="store_true", help="include gate-decided rows (default: discretionary only)"
    )
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set")

    reviewer_module = load_reviewer_module()
    cohort = load_manifest(args.cohort, discretionary_only=not args.all_gates)
    if args.limit:
        cohort = cohort[: args.limit]
    arm_slug = args.arm if args.arm in ("asrun", "current") else Path(args.arm).stem
    out_dir = data_dir() / "results" / f"{args.cohort}_{arm_slug}_rep{args.rep}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"cohort {args.cohort}, arm {arm_slug}, rep {args.rep}: {len(cohort)} rows -> {out_dir}")
    semaphore = asyncio.Semaphore(CONCURRENCY)
    tasks = [replay_one(row, args.arm, args.rep, args.repo, reviewer_module, semaphore, out_dir) for row in cohort]
    statuses = await asyncio.gather(*tasks)
    for status in sorted(set(statuses)):
        print(f"  {status}: {statuses.count(status)}")


if __name__ == "__main__":
    asyncio.run(main())
