#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyyaml",
# ]
# ///
# ruff: noqa: T201
"""Decide what to do with Stamphog's prior approval after a push.

Reads `REPO`, `PR_NUMBER`, `HEAD_SHA`, `BASE_REF`, `GITHUB_WORKSPACE` from
the environment and prints a single-line `Decision` JSON on stdout:

    {"dismiss_approval": bool, "run_review": bool, "reason": "...", "last_approved_sha": "..."}

The two booleans are orthogonal so each downstream workflow job gates on
exactly the question it owns: the `dismiss` job reads `dismiss_approval`,
the `review` job reads `run_review`. Decisions are constructed only via
`Decision.retain`, `Decision.review_only`, `Decision.dismiss_and_review`,
and `Decision.error` — together they cover every legitimate combination,
and the impossible "dismiss the approval but skip re-review" case is
unrepresentable.

Anything ambiguous (mixed paths, fetch error, foreign-branch merge) falls
through to `Decision.dismiss_and_review`. The bias is correctness, not
retention.

A commit can also clear the bar by carrying an approval from elsewhere in the
PR's stack, which is what makes folding a reviewed stack back into one PR free
of a re-stamp. `stack_credit` owns that lookup and the invariants behind it;
this module only asks it whether a given commit's content was already approved.
Rewritten history is the one case where credit changes the shape of the check
rather than just the verdict: after a force-push there is no delta to walk, so
every commit in the PR has to clear the bar on its own.
"""

import os
import sys
import json
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path

import stack_credit
from gates import is_trivial_at_dismiss_time
from stack_credit import (
    Approval,
    change_key,
    is_ancestor as _is_ancestor,
    merge_base,
)

# Stamphog now approves only as stamphog[bot] (the app), carrying the review
# body. github-actions[bot] is kept here so legacy bodyless approvals from
# before that change still count as a prior bot approval for the delta check.
BOT_LOGINS = {"github-actions[bot]", "stamphog[bot]"}


class Reason(StrEnum):
    """Why the decision was made. Plumbed into the dismissal message and PR comment.

    `error:<ExcName>` is constructed dynamically in `Decision.error` for
    unhandled exceptions and is intentionally not enumerated here.
    """

    TRIVIAL_PATHS = "trivial_paths"
    MERGE_ONLY = "merge_only"
    MIXED_TRIVIAL = "mixed_trivial"
    APPROVED_ELSEWHERE = "approved_elsewhere"
    REWRITTEN_BUT_APPROVED = "rewritten_but_approved"
    NON_TRIVIAL_DELTA = "non_trivial_delta"
    NON_LINEAR_HISTORY = "non_linear_history"
    EMPTY_DELTA = "empty_delta"
    NO_PRIOR_APPROVAL = "no_prior_approval"


class CommitClass(StrEnum):
    """Per-commit classification used to fold a delta into a single decision."""

    MERGE = "merge"
    TRIVIAL = "trivial"
    APPROVED_ELSEWHERE = "approved_elsewhere"
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
    def review_only(cls, reason: Reason) -> "Decision":
        """No prior bot approval to dismiss, but the label is still on and the
        agent hasn't approved yet — re-run the review on this push. Covers the
        first-run ERROR case (LLM backend was down, so the label was retained
        without an approval): the push actually retries the review instead of
        leaving the PR labeled but stuck until someone re-applies the label."""
        return cls(dismiss_approval=False, run_review=True, reason=reason)

    @classmethod
    def error(cls, exc: Exception) -> "Decision":
        """Defense-in-depth fallback when the script itself crashes."""
        return cls.dismiss_and_review(f"error:{type(exc).__name__}")


def _run(*args: str, cwd: Path | None = None) -> str:
    """Run command, return stdout. Raises on non-zero exit."""
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, timeout=30, check=True).stdout


def select_last_bot_approval(reviews: list[dict]) -> Approval | None:
    """Pick the most recent bot APPROVED review.

    Pure function so the filter+sort behavior can be exercised without
    invoking `gh api`. Human reviews and non-APPROVED bot reviews are
    excluded; ties are broken by `submitted_at`.
    """
    bot_approvals = sorted(
        (r for r in reviews if r.get("user", {}).get("login") in BOT_LOGINS and r.get("state") == "APPROVED"),
        key=lambda r: r.get("submitted_at", ""),
    )
    if not bot_approvals:
        return None
    latest = bot_approvals[-1]
    commit_id = latest.get("commit_id")
    if not commit_id:
        return None
    return Approval(sha=commit_id, submitted_at=latest.get("submitted_at", ""))


def find_last_approval(repo: str, pr_number: int) -> Approval | None:
    """Most recent Stamphog-bot APPROVED review on `pr_number`."""
    reviews = json.loads(_run("gh", "api", f"repos/{repo}/pulls/{pr_number}/reviews", "--paginate"))
    return select_last_bot_approval(reviews)


def _has_conflict_resolution_edits(sha: str, cwd: Path) -> bool:
    """Whether a merge commit carries edits beyond what merging its parents produced."""
    return bool(_run("git", "show", sha, "--diff-merges=cc", "--format=", "-p", cwd=cwd).strip())


def _first_parent_commits_between(from_sha: str, to_sha: str, cwd: Path) -> list[str]:
    """Return commits in `(from_sha, to_sha]`, oldest first."""
    commit_range = f"{from_sha}..{to_sha}"
    output = _run("git", "rev-list", "--reverse", "--first-parent", commit_range, cwd=cwd)
    return output.splitlines()


class StackCredit:
    """Answers what this PR's stack has already had approved.

    The stack walk behind `provider` costs several GitHub API calls and a ref
    fetch per layer, and most pushes reach a verdict without it, so it runs at
    most once and only once a commit has already failed the cheaper local
    checks. A None provider disables credit entirely, which is what keeps
    `evaluate_delta` callable as a pure git-only function.
    """

    def __init__(self, provider: Callable[[], stack_credit.Credit] | None) -> None:
        self._provider = provider
        self._credit: stack_credit.Credit | None = None

    def _load(self) -> stack_credit.Credit:
        if self._credit is None:
            try:
                self._credit = self._provider() if self._provider else stack_credit.Credit.none()
            except Exception as exc:
                # Granting no credit leaves the caller dismissing exactly as it
                # did before credit existed, so a GitHub or git failure here is
                # reported against the real delta reason rather than collapsing
                # the whole decision into `error:<ExcName>`.
                print(f"[dismiss_check] stack credit unavailable: {exc}", file=sys.stderr)
                self._credit = stack_credit.Credit.none()
        return self._credit

    def covers(self, sha: str, cwd: Path) -> bool:
        if self._provider is None:
            return False
        key = change_key(sha, cwd)
        if key is None:
            return False
        return key in self._load().change_keys

    def reaches_approved_tip(self, sha: str, cwd: Path) -> bool:
        if self._provider is None:
            return False
        return any(_is_ancestor(sha, tip, cwd) for tip in self._load().approved_tips)


def _classify_merge(sha: str, foreign_parents: list[str], cwd: Path, base_ref: str, credit: StackCredit) -> CommitClass:
    """Classify a merge by where the content it pulls in came from.

    A merge has no diff of its own to key on, so it is judged by its non-first
    parents. Reachable from `base_ref` is the ordinary "merged master in" case.
    Reachable from a stack tip is the fold: merging a layer into the PR below
    produces exactly this shape, and that layer carries its own approval.
    Anything else is an arbitrary side branch nobody reviewed.
    """
    if _has_conflict_resolution_edits(sha, cwd):
        return CommitClass.NON_TRIVIAL
    if all(_is_ancestor(p, base_ref, cwd) for p in foreign_parents):
        return CommitClass.MERGE
    if all(_is_ancestor(p, base_ref, cwd) or credit.reaches_approved_tip(p, cwd) for p in foreign_parents):
        return CommitClass.APPROVED_ELSEWHERE
    return CommitClass.NON_TRIVIAL


def _classify_commit(sha: str, cwd: Path, base_ref: str, credit: StackCredit) -> CommitClass:
    parents = _run("git", "rev-list", "--parents", "-n", "1", sha, cwd=cwd).split()[1:]
    if len(parents) >= 2:
        return _classify_merge(sha, parents[1:], cwd, base_ref, credit)
    files = [f for f in _run("git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha, cwd=cwd).splitlines() if f]
    if all(is_trivial_at_dismiss_time(f) for f in files):
        return CommitClass.TRIVIAL
    if credit.covers(sha, cwd):
        return CommitClass.APPROVED_ELSEWHERE
    return CommitClass.NON_TRIVIAL


def _evaluate_rewritten(head_sha: str, cwd: Path, base_ref: str, credit: StackCredit) -> Decision:
    """Decide a force-pushed branch, where there is no delta left to walk.

    A rewrite invalidates the incremental question, so this asks the whole
    question instead: every commit the PR now contains has to be trivial, a
    clean merge from base, or content Stamphog already approved somewhere in
    the stack. Requiring at least one approved commit is what separates a
    rebase that preserved reviewed work from a force-push that replaced it with
    an unrelated branch that happens to touch only trivial paths.
    """
    fork_point = merge_base(base_ref, head_sha, cwd)
    if fork_point is None:
        return Decision.dismiss_and_review(Reason.NON_LINEAR_HISTORY)

    commits = _first_parent_commits_between(fork_point, head_sha, cwd)
    if not commits:
        return Decision.dismiss_and_review(Reason.NON_LINEAR_HISTORY)

    classes = [_classify_commit(c, cwd, base_ref, credit) for c in commits]
    if CommitClass.NON_TRIVIAL in classes or CommitClass.APPROVED_ELSEWHERE not in classes:
        return Decision.dismiss_and_review(Reason.NON_LINEAR_HISTORY)
    return Decision.retain(Reason.REWRITTEN_BUT_APPROVED)


def evaluate_delta(
    last_approved_sha: str,
    head_sha: str,
    cwd: Path,
    base_ref: str = "origin/master",
    credit_provider: Callable[[], stack_credit.Credit] | None = None,
) -> Decision:
    """Classify the first-parent commit delta from `last_approved_sha` to `head_sha`.

    First-parent walking ensures a merge from base appears as a single
    node — without it, the second-parent's commits would surface
    individually and almost always classify as non-trivial.
    """
    credit = StackCredit(credit_provider)
    if not _is_ancestor(last_approved_sha, head_sha, cwd):
        return _evaluate_rewritten(head_sha, cwd, base_ref, credit)

    commits = _first_parent_commits_between(last_approved_sha, head_sha, cwd)
    if not commits:
        return Decision.retain(Reason.EMPTY_DELTA)

    classes = [_classify_commit(c, cwd, base_ref, credit) for c in commits]
    if CommitClass.NON_TRIVIAL in classes:
        return Decision.dismiss_and_review(Reason.NON_TRIVIAL_DELTA)
    if CommitClass.APPROVED_ELSEWHERE in classes:
        return Decision.retain(Reason.APPROVED_ELSEWHERE)
    if CommitClass.MERGE in classes and CommitClass.TRIVIAL in classes:
        return Decision.retain(Reason.MIXED_TRIVIAL)
    if CommitClass.MERGE in classes:
        return Decision.retain(Reason.MERGE_ONLY)
    return Decision.retain(Reason.TRIVIAL_PATHS)


def decide(repo: str, pr_number: int, head_sha: str, cwd: Path, base_ref: str = "origin/master") -> Decision:
    approval = find_last_approval(repo, pr_number)
    if approval is None:
        return Decision.review_only(Reason.NO_PRIOR_APPROVAL)

    def credit_provider() -> stack_credit.Credit:
        return stack_credit.collect_credit(
            repo=repo,
            pr_number=pr_number,
            own_approval=approval,
            cwd=cwd,
            base_ref=base_ref,
            find_approval=find_last_approval,
        )

    return replace(
        evaluate_delta(approval.sha, head_sha, cwd, base_ref, credit_provider),
        last_approved_sha=approval.sha,
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
