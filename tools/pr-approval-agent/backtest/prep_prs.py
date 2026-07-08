#!/usr/bin/env python3
# ruff: noqa: T201
"""Prepare PR diffs and outcome labels from git alone (zero GitHub API calls).

For every manifest row:
  1. fetch refs/pull/<N>/head into refs/backtest/<N> (batched)
  2. resolve the review-time head: newest commit on the PR head whose committer
     date is <= the review timestamp (post-review rebases rewrite committer
     dates, so a row can resolve to None; harvest head shas cover those when
     the traced-path events carried them)
  3. write the diff (merge-base with origin/master ... head) to data/diffs/<N>.patch
  4. label the outcome: merged (squash subject "(#N)" on origin/master),
     merged_unchanged (merged and no commits after the review), days_to_merge

Outputs data/labels.jsonl. Existing diffs are kept unless --force.

Usage: python3 prep_prs.py [--repo <checkout>] [--cohort <version>]
"""

from __future__ import annotations

import re
import json
import argparse
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from backtest_lib import data_dir, load_manifest

SUBJECT_PR_RE = re.compile(r"\(#(\d+)\)\s*$")


def run_git(repo: Path, args: list[str], check: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}...: {result.stderr.strip()[:200]}")
    return result.stdout


def batched_fetch(repo: Path, pr_numbers: list[int]) -> None:
    refspecs = [f"+refs/pull/{n}/head:refs/backtest/{n}" for n in pr_numbers]
    for i in range(0, len(refspecs), 100):
        chunk = refspecs[i : i + 100]
        result = subprocess.run(
            ["git", "-C", str(repo), "fetch", "--no-tags", "origin", *chunk],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"  fetch chunk {i}: {result.stderr.strip()[:200]}")
        print(f"  fetched {min(i + 100, len(refspecs))}/{len(refspecs)} pull refs")


def head_at_review(repo: Path, pr: int, review_ts: datetime) -> str | None:
    out = run_git(repo, ["rev-list", "--format=%H %cI", "--no-commit-header", f"refs/backtest/{pr}"], check=False)
    for line in out.splitlines():
        sha, iso = line.split(" ", 1)
        if datetime.fromisoformat(iso) <= review_ts:
            return sha
    return None


def build_subject_index(repo: Path, days: int = 90) -> dict[int, tuple[str, str]]:
    """Map PR number -> (merge sha, committer date ISO) from origin/master squash subjects."""
    out = run_git(repo, ["log", "origin/master", f"--since={days} days ago", "--format=%H|%cI|%s"])
    index: dict[int, tuple[str, str]] = {}
    for line in out.splitlines():
        sha, iso, subject = line.split("|", 2)
        match = SUBJECT_PR_RE.search(subject)
        if match:
            index.setdefault(int(match.group(1)), (sha, iso))
    return index


def write_diff(repo: Path, pr: int, head: str, force: bool) -> bool:
    patch = data_dir() / "diffs" / f"{pr}.patch"
    if patch.exists() and not force:
        return True
    base = run_git(repo, ["merge-base", "origin/master", head], check=False).strip()
    if not base:
        return False
    diff = run_git(repo, ["diff", f"{base}...{head}"], check=False)
    if not diff:
        return False
    patch.write_text(diff)
    return True


def label_row(repo: Path, row: dict, subject_index: dict[int, tuple[str, str]], force: bool) -> dict:
    pr = int(row["pr"])
    review_ts = datetime.fromisoformat(row["ts_last"]).astimezone(UTC)
    head = head_at_review(repo, pr, review_ts)
    if head is None and row.get("commit"):
        # Traced-path events recorded the exact reviewed head; use it when the
        # date walk fails (post-review rebase).
        head = row["commit"]
    merged = subject_index.get(pr)
    tip = run_git(repo, ["rev-parse", f"refs/backtest/{pr}"], check=False).strip()
    label = {
        "cohort": row["cohort"],
        "pr": pr,
        "trace_id": row.get("trace_id"),
        "final_verdict": row.get("final_verdict"),
        "head_at_review": head,
        "merged": merged is not None,
        "merged_at": merged[1] if merged else None,
        # No commits after the review and it merged: the reviewed state shipped as-is.
        "merged_unchanged": merged is not None and head is not None and head == tip,
        "has_diff": bool(head and write_diff(repo, pr, head, force)),
    }
    if merged:
        delta = datetime.fromisoformat(merged[1]) - review_ts
        label["days_to_merge"] = round(delta.total_seconds() / 86400, 2)
    return label


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--cohort", help="limit to one cohort (default: all)")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    (data_dir() / "diffs").mkdir(parents=True, exist_ok=True)
    rows = load_manifest(cohort=args.cohort, discretionary_only=False)
    print(f"{len(rows)} manifest rows")

    run_git(args.repo, ["fetch", "--no-tags", "origin", "master"], check=False)
    batched_fetch(args.repo, sorted({int(r["pr"]) for r in rows}))
    subject_index = build_subject_index(args.repo)

    labels = [label_row(args.repo, row, subject_index, args.force) for row in rows]
    with (data_dir() / "labels.jsonl").open("w") as fh:
        for label in labels:
            fh.write(json.dumps(label) + "\n")

    merged_n = sum(1 for label in labels if label["merged"])
    unchanged_n = sum(1 for label in labels if label["merged_unchanged"])
    diffs_n = sum(1 for label in labels if label["has_diff"])
    print(f"labels: {len(labels)} rows, {merged_n} merged, {unchanged_n} merged unchanged, {diffs_n} diffs written")


if __name__ == "__main__":
    main()
