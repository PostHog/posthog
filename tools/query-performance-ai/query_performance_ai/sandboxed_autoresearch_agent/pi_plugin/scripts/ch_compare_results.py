#!/usr/bin/env python3
"""Compare a candidate result set to the saved baseline.

Exit codes: 0 match, 1 mismatch, 2 comparator crashed.
"""

from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import AutoresearchError, require_file  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--candidate-result", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def _resolve_candidate(workspace: Path, provided: Path | None) -> Path:
    if provided is not None:
        return provided
    last_run = workspace / "runtime" / "last_run.json"
    require_file(last_run)
    data = json.loads(last_run.read_text())
    candidate = data.get("result_file")
    if not candidate:
        raise AutoresearchError(f"no result_file in {last_run}")
    return Path(candidate)


def _resolve_output(candidate: Path, provided: Path | None) -> Path:
    if provided is not None:
        return provided
    return candidate.parent / "comparison.json"


def _normalize_jsonl(text: str) -> list[str]:
    """Reserialize defensively so a future change to the proxy's output
    shape can't silently produce false mismatches. Non-JSON lines are
    kept verbatim so they surface as mismatches, not silent drops."""
    normalized: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            normalized.append(raw)
            continue
        normalized.append(json.dumps(parsed, separators=(",", ":"), sort_keys=True))
    return normalized


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    workspace: Path = args.workspace
    baseline_result = workspace / "baseline" / "result.jsonl"
    require_file(baseline_result)

    candidate_result = _resolve_candidate(workspace, args.candidate_result)
    require_file(candidate_result)

    output_file = _resolve_output(candidate_result, args.output)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    baseline_lines = sorted(_normalize_jsonl(baseline_result.read_text()))
    candidate_lines = sorted(_normalize_jsonl(candidate_result.read_text()))

    rows_baseline = len(baseline_lines)
    rows_candidate = len(candidate_lines)

    if baseline_lines == candidate_lines:
        output_file.write_text(
            json.dumps(
                {
                    "matches": True,
                    "mode": "sorted-line",
                    "summary": "exact match after sorting",
                    "details": {"rows_baseline": rows_baseline, "rows_candidate": rows_candidate},
                },
                indent=2,
            )
            + "\n"
        )
        print(f"comparison: match ({rows_candidate} rows)")
        return 0

    # Build a diff sample. Hoist the sets out of the comprehensions so the
    # mismatch path stays O(N) instead of rebuilding the set every iteration.
    baseline_set = set(baseline_lines)
    candidate_set = set(candidate_lines)
    extra_in_candidate = [ln for ln in candidate_lines if ln not in baseline_set][:10]
    missing_in_candidate = [ln for ln in baseline_lines if ln not in candidate_set][:10]
    diff_lines = len(extra_in_candidate) + len(missing_in_candidate)

    output_file.write_text(
        json.dumps(
            {
                "matches": False,
                "mode": "sorted-line",
                "summary": f"{diff_lines} lines differ",
                "details": {
                    "rows_baseline": rows_baseline,
                    "rows_candidate": rows_candidate,
                    "extra_in_candidate": extra_in_candidate,
                    "missing_in_candidate": missing_in_candidate,
                },
            },
            indent=2,
        )
        + "\n"
    )
    print(
        f"comparison: MISMATCH ({diff_lines} lines differ, baseline={rows_baseline} candidate={rows_candidate})",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    # Crashes must exit 2 — 1 is reserved for "real mismatch."
    try:
        sys.exit(main())
    except AutoresearchError as err:
        print(f"error: {err}", file=sys.stderr)
        sys.exit(2)
    except Exception as err:
        print(f"error: {err!r}", file=sys.stderr)
        sys.exit(2)
