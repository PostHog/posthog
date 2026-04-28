#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
# ruff: noqa: T201
"""Decide whether to retain or dismiss Stamphog's prior approval after a push.

Reads `REPO`, `PR_NUMBER`, `HEAD_SHA`, `BASE_REF`, `GITHUB_WORKSPACE` from
the environment, prints a single-line JSON verdict on stdout:

    {"action": "retain"|"dismiss", "reason": "...", "last_approved_sha": "..."}

Retains only when every new commit since the last bot approval is either
a clean merge from the base branch (no manual conflict resolution AND
foreign parents reachable from `BASE_REF`) or touches only paths in the
strict dismiss-time allow-list (see `gates.is_trivial_at_dismiss_time`).
Anything ambiguous — force-push, mixed paths, fetch error, foreign-branch
merge — falls through to `dismiss`. The bias is correctness, not retention.
"""

import os
import json
import subprocess
from pathlib import Path

from gates import is_trivial_at_dismiss_time

BOT_LOGIN = "github-actions[bot]"


def _run(*args: str, cwd: Path | None = None) -> str:
    """Run command, return stdout. Raises on non-zero exit."""
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, timeout=30, check=True).stdout


def _is_ancestor(ancestor: str, descendant: str, cwd: Path) -> bool:
    """`git merge-base --is-ancestor` uses returncode as the bool answer."""
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=cwd,
            timeout=30,
        ).returncode
        == 0
    )


def find_last_approved_sha(repo: str, pr_number: int) -> str | None:
    """Commit SHA of the most recent github-actions[bot] APPROVED review."""
    reviews = json.loads(_run("gh", "api", f"repos/{repo}/pulls/{pr_number}/reviews", "--paginate"))
    bot_approvals = sorted(
        (r for r in reviews if r.get("user", {}).get("login") == BOT_LOGIN and r.get("state") == "APPROVED"),
        key=lambda r: r.get("submitted_at", ""),
    )
    return bot_approvals[-1].get("commit_id") if bot_approvals else None


def _classify_commit(sha: str, cwd: Path, base_ref: str) -> str:
    """Return 'merge', 'trivial', or 'non_trivial' for a single commit.

    A merge counts as 'merge' only when its combined-condensed diff is
    empty (no manual conflict resolution) AND every foreign parent is
    reachable from `base_ref` — without the second check, a clean merge
    from an arbitrary side branch would be trusted as if it came from base.
    """
    parents = _run("git", "rev-list", "--parents", "-n", "1", sha, cwd=cwd).split()[1:]
    if len(parents) >= 2:
        cc = _run("git", "show", sha, "--diff-merges=cc", "--format=", "-p", cwd=cwd)
        if cc.strip():
            return "non_trivial"
        if not all(_is_ancestor(p, base_ref, cwd) for p in parents[1:]):
            return "non_trivial"
        return "merge"
    files = [f for f in _run("git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha, cwd=cwd).splitlines() if f]
    return "trivial" if all(is_trivial_at_dismiss_time(f) for f in files) else "non_trivial"


def evaluate_delta(last_approved_sha: str, head_sha: str, cwd: Path, base_ref: str = "origin/master") -> dict:
    """Classify the first-parent commit delta from `last_approved_sha` to `head_sha`.

    First-parent walking ensures a merge from base appears as a single
    node — without it, the second-parent's commits would surface
    individually and almost always classify as non-trivial.
    """
    if not _is_ancestor(last_approved_sha, head_sha, cwd):
        return {"action": "dismiss", "reason": "non_linear_history"}

    commits = [
        c
        for c in _run(
            "git", "rev-list", "--reverse", "--first-parent", f"{last_approved_sha}..{head_sha}", cwd=cwd
        ).splitlines()
        if c
    ]
    if not commits:
        return {"action": "retain", "reason": "empty_delta"}

    classes = [_classify_commit(c, cwd, base_ref) for c in commits]
    if "non_trivial" in classes:
        return {"action": "dismiss", "reason": "non_trivial_delta"}

    has_merge = "merge" in classes
    has_trivial = "trivial" in classes
    reason = "mixed_trivial" if has_merge and has_trivial else ("merge_only" if has_merge else "trivial_paths")
    return {"action": "retain", "reason": reason}


def decide(repo: str, pr_number: int, head_sha: str, cwd: Path, base_ref: str = "origin/master") -> dict:
    last_approved_sha = find_last_approved_sha(repo, pr_number)
    if last_approved_sha is None:
        return {"action": "dismiss", "reason": "no_prior_approval", "last_approved_sha": None}
    return {**evaluate_delta(last_approved_sha, head_sha, cwd, base_ref), "last_approved_sha": last_approved_sha}


def main() -> None:
    try:
        decision = decide(
            repo=os.environ["REPO"],
            pr_number=int(os.environ["PR_NUMBER"]),
            head_sha=os.environ["HEAD_SHA"],
            cwd=Path(os.environ.get("GITHUB_WORKSPACE", ".")),
            base_ref=os.environ.get("BASE_REF", "origin/master"),
        )
    except Exception as e:
        decision = {"action": "dismiss", "reason": f"error:{type(e).__name__}", "last_approved_sha": None}
    print(json.dumps(decision))


if __name__ == "__main__":
    main()
