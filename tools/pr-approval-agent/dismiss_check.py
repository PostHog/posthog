#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
# ruff: noqa: T201
"""Decide what to do with Stamphog's prior approval after a push.

Reads `REPO`, `PR_NUMBER`, `HEAD_SHA`, `BASE_REF`, `GITHUB_WORKSPACE` from
the environment and prints a single-line `Decision` JSON on stdout:

    {"dismiss_approval": bool, "run_review": bool, "reason": "...", "last_approved_sha": "..."}

The two booleans are orthogonal so each downstream workflow job gates on
exactly the question it owns: the `dismiss` job reads `dismiss_approval`,
the `review` job reads `run_review`. Decisions are constructed only via
`Decision.retain`, `Decision.dismiss_and_review`, `Decision.no_op`, and
`Decision.error` — together they cover every legitimate combination, and
the impossible "dismiss the approval but skip re-review" case is
unrepresentable.

Anything ambiguous (force-push, mixed paths, fetch error, foreign-branch
merge) falls through to `Decision.dismiss_and_review`. The bias is
correctness, not retention.
"""

import os
import sys
import json
import subprocess
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path

from gates import is_trivial_at_dismiss_time

BOT_LOGIN = "github-actions[bot]"


class Reason(StrEnum):
    """Why the decision was made. Plumbed into the dismissal message and PR comment.

    `error:<ExcName>` is constructed dynamically in `Decision.error` for
    unhandled exceptions and is intentionally not enumerated here.
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


@dataclass(frozen=True)
class Decision:
    """Wire format consumed by .github/workflows/pr-approval-agent.yml.

    Construct only via the four classmethod factories — together they
    enumerate every legitimate combination of the two booleans.
    """

    dismiss_approval: bool
    run_review: bool
    reason: str
    last_approved_sha: str | None = None

    @classmethod
    def retain(cls, reason: Reason) -> "Decision":
        """Trivial delta with a prior approval — leave both the approval and the review alone."""
        return cls(dismiss_approval=False, run_review=False, reason=reason)

    @classmethod
    def dismiss_and_review(cls, reason: Reason | str) -> "Decision":
        """Non-trivial delta (or ambiguous fallback) — clear the prior approval and re-run review."""
        return cls(dismiss_approval=True, run_review=True, reason=str(reason))

    @classmethod
    def no_op(cls, reason: Reason) -> "Decision":
        """No prior approval to act on — nothing to do; the original `labeled`
        event already fired a review, and the label-strip on non-APPROVED is
        the canonical kill-switch. If a human dismissed the bot approval and
        kept the label, they can re-label to request a fresh review."""
        return cls(dismiss_approval=False, run_review=False, reason=reason)

    @classmethod
    def error(cls, exc: Exception) -> "Decision":
        """Defense-in-depth fallback when the script itself crashes."""
        return cls.dismiss_and_review(f"error:{type(exc).__name__}")


def _run(*args: str, cwd: Path | None = None) -> str:
    """Run command, return stdout. Raises on non-zero exit."""
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, timeout=30, check=True).stdout


def _is_ancestor(ancestor: str, descendant: str, cwd: Path) -> bool:
    """`git merge-base --is-ancestor`: rc 0=ancestor, 1=not ancestor, ≥2=error.

    Errors fall through to False so callers treat the relation as
    non-linear and dismiss + re-review (fail-closed). The stderr log
    distinguishes a real force-push from a git plumbing failure.
    """
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode not in (0, 1):
        print(
            f"[dismiss_check] _is_ancestor git error rc={result.returncode}: {result.stderr.strip()}",
            file=sys.stderr,
        )
    return result.returncode == 0


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


def _first_parent_commits_between(from_sha: str, to_sha: str, cwd: Path) -> list[str]:
    """Return commits in `(from_sha, to_sha]`, oldest first."""
    commit_range = f"{from_sha}..{to_sha}"
    output = _run("git", "rev-list", "--reverse", "--first-parent", commit_range, cwd=cwd)
    return output.splitlines()


def _classify_commit(sha: str, cwd: Path, base_ref: str) -> CommitClass:
    parents = _run("git", "rev-list", "--parents", "-n", "1", sha, cwd=cwd).split()[1:]
    if len(parents) >= 2:
        return (
            CommitClass.MERGE if _is_clean_merge_from_base(sha, parents[1:], cwd, base_ref) else CommitClass.NON_TRIVIAL
        )
    files = [f for f in _run("git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha, cwd=cwd).splitlines() if f]
    return CommitClass.TRIVIAL if all(is_trivial_at_dismiss_time(f) for f in files) else CommitClass.NON_TRIVIAL


def evaluate_delta(last_approved_sha: str, head_sha: str, cwd: Path, base_ref: str = "origin/master") -> Decision:
    """Classify the first-parent commit delta from `last_approved_sha` to `head_sha`.

    First-parent walking ensures a merge from base appears as a single
    node — without it, the second-parent's commits would surface
    individually and almost always classify as non-trivial.
    """
    if not _is_ancestor(last_approved_sha, head_sha, cwd):
        return Decision.dismiss_and_review(Reason.NON_LINEAR_HISTORY)

    commits = _first_parent_commits_between(last_approved_sha, head_sha, cwd)
    if not commits:
        return Decision.retain(Reason.EMPTY_DELTA)

    classes = [_classify_commit(c, cwd, base_ref) for c in commits]
    if CommitClass.NON_TRIVIAL in classes:
        return Decision.dismiss_and_review(Reason.NON_TRIVIAL_DELTA)
    if CommitClass.MERGE in classes and CommitClass.TRIVIAL in classes:
        return Decision.retain(Reason.MIXED_TRIVIAL)
    if CommitClass.MERGE in classes:
        return Decision.retain(Reason.MERGE_ONLY)
    return Decision.retain(Reason.TRIVIAL_PATHS)


def decide(repo: str, pr_number: int, head_sha: str, cwd: Path, base_ref: str = "origin/master") -> Decision:
    last_approved_sha = find_last_approved_sha(repo, pr_number)
    if last_approved_sha is None:
        return Decision.no_op(Reason.NO_PRIOR_APPROVAL)
    return replace(
        evaluate_delta(last_approved_sha, head_sha, cwd, base_ref),
        last_approved_sha=last_approved_sha,
    )


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
        decision = Decision.error(e)
    print(json.dumps(asdict(decision)))


if __name__ == "__main__":
    main()
