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
from enum import StrEnum
from pathlib import Path

from gates import is_trivial_at_dismiss_time

BOT_LOGIN = "github-actions[bot]"


class Action(StrEnum):
    """Top-level decision. Wire format consumed by the workflow YAML."""

    RETAIN = "retain"
    DISMISS = "dismiss"


class Reason(StrEnum):
    """Why the decision was made. Plumbed into the dismissal message and PR comment.

    `error:<ExcName>` is constructed dynamically in `main()` for unhandled
    exceptions and is intentionally not enumerated here.
    """

    TRIVIAL_PATHS = "trivial_paths"
    MERGE_ONLY = "merge_only"
    MIXED_TRIVIAL = "mixed_trivial"
    NON_TRIVIAL_DELTA = "non_trivial_delta"
    NON_LINEAR_HISTORY = "non_linear_history"
    EMPTY_DELTA = "empty_delta"
    NO_PRIOR_APPROVAL = "no_prior_approval"


class CommitClass(StrEnum):
    """Per-commit classification used to fold a delta into a single decision."""

    MERGE = "merge"
    TRIVIAL = "trivial"
    NON_TRIVIAL = "non_trivial"


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


def select_last_bot_approval(reviews: list[dict]) -> str | None:
    """Pick the commit SHA of the most recent bot APPROVED review.

    Pure function so the filter+sort behavior can be exercised without
    invoking `gh api`. Human reviews and non-APPROVED bot reviews are
    excluded; ties are broken by `submitted_at`.
    """
    bot_approvals = sorted(
        (r for r in reviews if r.get("user", {}).get("login") == BOT_LOGIN and r.get("state") == "APPROVED"),
        key=lambda r: r.get("submitted_at", ""),
    )
    return bot_approvals[-1].get("commit_id") if bot_approvals else None


def find_last_approved_sha(repo: str, pr_number: int) -> str | None:
    """Commit SHA of the most recent github-actions[bot] APPROVED review."""
    reviews = json.loads(_run("gh", "api", f"repos/{repo}/pulls/{pr_number}/reviews", "--paginate"))
    return select_last_bot_approval(reviews)


def _is_clean_merge_from_base(sha: str, foreign_parents: list[str], cwd: Path, base_ref: str) -> bool:
    """A merge is clean iff it added no manual conflict-resolution edits AND
    every non-first parent is already reachable from `base_ref`.

    Without the ancestry check, a clean merge from an arbitrary side branch
    would be trusted as if it came from base.
    """
    cc = _run("git", "show", sha, "--diff-merges=cc", "--format=", "-p", cwd=cwd)
    if cc.strip():
        return False
    return all(_is_ancestor(p, base_ref, cwd) for p in foreign_parents)


def _classify_commit(sha: str, cwd: Path, base_ref: str) -> CommitClass:
    parents = _run("git", "rev-list", "--parents", "-n", "1", sha, cwd=cwd).split()[1:]
    if len(parents) >= 2:
        return (
            CommitClass.MERGE if _is_clean_merge_from_base(sha, parents[1:], cwd, base_ref) else CommitClass.NON_TRIVIAL
        )
    files = [f for f in _run("git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha, cwd=cwd).splitlines() if f]
    return CommitClass.TRIVIAL if all(is_trivial_at_dismiss_time(f) for f in files) else CommitClass.NON_TRIVIAL


def evaluate_delta(last_approved_sha: str, head_sha: str, cwd: Path, base_ref: str = "origin/master") -> dict:
    """Classify the first-parent commit delta from `last_approved_sha` to `head_sha`.

    First-parent walking ensures a merge from base appears as a single
    node — without it, the second-parent's commits would surface
    individually and almost always classify as non-trivial.
    """
    if not _is_ancestor(last_approved_sha, head_sha, cwd):
        return {"action": Action.DISMISS, "reason": Reason.NON_LINEAR_HISTORY}

    commits = [
        c
        for c in _run(
            "git", "rev-list", "--reverse", "--first-parent", f"{last_approved_sha}..{head_sha}", cwd=cwd
        ).splitlines()
        if c
    ]
    if not commits:
        return {"action": Action.RETAIN, "reason": Reason.EMPTY_DELTA}

    classes = [_classify_commit(c, cwd, base_ref) for c in commits]
    if CommitClass.NON_TRIVIAL in classes:
        return {"action": Action.DISMISS, "reason": Reason.NON_TRIVIAL_DELTA}
    if CommitClass.MERGE in classes and CommitClass.TRIVIAL in classes:
        return {"action": Action.RETAIN, "reason": Reason.MIXED_TRIVIAL}
    if CommitClass.MERGE in classes:
        return {"action": Action.RETAIN, "reason": Reason.MERGE_ONLY}
    return {"action": Action.RETAIN, "reason": Reason.TRIVIAL_PATHS}


def decide(repo: str, pr_number: int, head_sha: str, cwd: Path, base_ref: str = "origin/master") -> dict:
    last_approved_sha = find_last_approved_sha(repo, pr_number)
    if last_approved_sha is None:
        return {"action": Action.DISMISS, "reason": Reason.NO_PRIOR_APPROVAL, "last_approved_sha": None}
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
        decision = {"action": Action.DISMISS, "reason": f"error:{type(e).__name__}", "last_approved_sha": None}
    print(json.dumps(decision))


if __name__ == "__main__":
    main()
