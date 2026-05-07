#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
# ruff: noqa: T201
"""Fast, offline pre-push check: scan newly-added comment lines for leaks.

Runs from `.husky/pre-push`. Reads the unified diff between the local
branch tip and its remote-tracking commit (or `origin/master` if there's
no upstream yet), extracts only newly-added comment lines, and applies
the same regex patterns as the CI bot.

Behaviour:
- 0 hits → silent exit 0.
- Only `warn`/`redact` hits → print a friendly summary, exit 0 (push proceeds).
- Any `block` hit (looks like a real secret) → print the offending lines,
  exit 1 (push blocked). Author can override with `git push --no-verify`
  if the finding is a false positive — same escape hatch as every other
  husky hook in this repo.

The script is intentionally dependency-free (only stdlib) so it runs
without flox / uv / venv setup. It imports the shared `patterns` module
from the same directory.
"""

from __future__ import annotations

import os
import sys
import argparse
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from comment_scanner import CommentHit, format_hits_table, scan_diff_added_lines  # noqa: E402

COLOR_RED = "\033[31m"
COLOR_YELLOW = "\033[33m"
COLOR_DIM = "\033[2m"
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"


def _run(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=check)


def _resolve_diff_range() -> str | None:
    """Pick a sane base for the diff.

    Order:
    1. The upstream of the current branch (`@{upstream}`) — what the push
       would update.
    2. `origin/master` — best fallback before a branch has tracked anything.
    3. The merge-base with master — covers detached HEAD.
    """
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()

    upstream = _run(["git", "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"])
    if upstream.returncode == 0 and upstream.stdout.strip():
        return f"{upstream.stdout.strip()}...HEAD"

    for fallback in ("origin/master", "origin/main"):
        rev = _run(["git", "rev-parse", "--verify", fallback])
        if rev.returncode == 0:
            base = _run(["git", "merge-base", fallback, "HEAD"])
            if base.returncode == 0 and base.stdout.strip():
                return f"{base.stdout.strip()}...HEAD"

    return None


def _read_diff_from_stdin_refs() -> str:
    """Husky pre-push receives `<local_ref> <local_sha> <remote_ref> <remote_sha>` on stdin.

    When present, we use the (remote_sha → local_sha) range to scan exactly
    what's about to ship, including the case where the user is pushing
    multiple branches. If no input or empty/zero shas, fall back to the
    upstream-based range.
    """
    if sys.stdin.isatty():
        return ""

    payload = sys.stdin.read().strip()
    if not payload:
        return ""

    diffs: list[str] = []
    for line in payload.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local_sha, remote_sha = parts[1], parts[3]
        if local_sha == "0" * 40:
            # Branch deletion — nothing to scan.
            continue
        if remote_sha == "0" * 40:
            # New branch — diff against origin/master merge-base.
            for fallback in ("origin/master", "origin/main"):
                rev = _run(["git", "rev-parse", "--verify", fallback])
                if rev.returncode == 0:
                    base = _run(["git", "merge-base", fallback, local_sha])
                    if base.returncode == 0 and base.stdout.strip():
                        result = _run(["git", "diff", f"{base.stdout.strip()}...{local_sha}"])
                        diffs.append(result.stdout)
                        break
        else:
            result = _run(["git", "diff", f"{remote_sha}...{local_sha}"])
            diffs.append(result.stdout)

    return "\n".join(diffs)


def _get_diff() -> str:
    diff = _read_diff_from_stdin_refs()
    if diff:
        return diff

    range_spec = _resolve_diff_range()
    if not range_spec:
        return ""
    result = _run(["git", "diff", range_spec])
    return result.stdout


def _print_hits(hits: list[CommentHit], *, max_hits: int = 25) -> None:
    blockers = [h for h in hits if h.finding.severity == "block"]
    warnings = [h for h in hits if h.finding.severity != "block"]

    if blockers:
        print(
            f"\n{COLOR_RED}{COLOR_BOLD}🛑 pr-leak-guard: secret-shaped content in newly-added comments{COLOR_RESET}\n"
        )
        print(format_hits_table(blockers[:max_hits]))
        if len(blockers) > max_hits:
            print(f"  ... and {len(blockers) - max_hits} more.")
        print(
            f"\n{COLOR_BOLD}This looks like a real secret.{COLOR_RESET} "
            "Remove or replace it before pushing.\n"
            "If this is a false positive, push with --no-verify and add an explanation in the PR.\n"
        )

    if warnings:
        print(
            f"\n{COLOR_YELLOW}{COLOR_BOLD}⚠  pr-leak-guard: possible sensitive content in newly-added comments{COLOR_RESET}\n"
        )
        print(format_hits_table(warnings[:max_hits]))
        if len(warnings) > max_hits:
            print(f"  ... and {len(warnings) - max_hits} more.")
        print(f"\n{COLOR_DIM}This is a heads-up. The push will proceed; review the lines above.{COLOR_RESET}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-push leak check on staged comments.")
    parser.add_argument(
        "--diff-file",
        type=str,
        help="Read diff from this path instead of git (for tests / dry-run)",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if os.environ.get("POSTHOG_LEAK_GUARD_DISABLE") == "1":
        return 0

    if args.diff_file:
        diff = Path(args.diff_file).read_text(encoding="utf-8", errors="ignore")
    else:
        diff = _get_diff()

    if not diff.strip():
        return 0

    hits = scan_diff_added_lines(diff)
    if not hits:
        return 0

    _print_hits(hits)

    if any(h.finding.severity == "block" for h in hits):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
