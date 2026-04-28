#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "posthoganalytics",
# ]
# ///
# ruff: noqa: T201
"""Decide whether to retain or dismiss Stamphog's prior approval after a push.

Run by the `decide-delta` job in pr-approval-agent.yml on `synchronize`
events. Emits one JSON line on stdout:

    {"action": "retain"|"dismiss", "reason": "...", "last_approved_sha": "..."}

Retains approval only when every commit since the last bot approval is
either (a) a clean merge from the base branch with no manual conflict
resolution, or (b) touches only paths in the strict dismiss-time
allow-list (see `is_trivial_at_dismiss_time` in gates.py). Anything
ambiguous (force-push, mixed paths, fetch failure) falls through to
`dismiss` — the bias is correctness, not retention.
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path
from typing import Any

from gates import is_trivial_at_dismiss_time

try:
    import posthoganalytics

    posthoganalytics.api_key = os.environ.get("POSTHOG_API_KEY", "")  # ty: ignore[invalid-assignment]
    posthoganalytics.host = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")  # ty: ignore[invalid-assignment]
    _POSTHOG_AVAILABLE = bool(posthoganalytics.api_key)
except ImportError:
    _POSTHOG_AVAILABLE = False


BOT_LOGIN = "github-actions[bot]"


# ── Subprocess helpers ───────────────────────────────────────────


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _git_ok(*args: str, cwd: Path) -> str:
    result = _git(*args, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _gh_api(endpoint: str, *, paginate: bool = False) -> Any:
    cmd = ["gh", "api", endpoint]
    if paginate:
        cmd.append("--paginate")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"gh api {endpoint} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


# ── GitHub: locate prior approval ────────────────────────────────


def find_last_approved_sha(repo: str, pr_number: int) -> str | None:
    """SHA of the most recent github-actions[bot] APPROVED review, or None."""
    reviews = _gh_api(f"repos/{repo}/pulls/{pr_number}/reviews", paginate=True)
    bot_approvals = [r for r in reviews if r.get("user", {}).get("login") == BOT_LOGIN and r.get("state") == "APPROVED"]
    if not bot_approvals:
        return None
    bot_approvals.sort(key=lambda r: r.get("submitted_at", ""), reverse=True)
    return bot_approvals[0].get("commit_id")


# ── Git: per-commit classification ───────────────────────────────


def is_ancestor(ancestor_sha: str, descendant_sha: str, cwd: Path) -> bool:
    return _git("merge-base", "--is-ancestor", ancestor_sha, descendant_sha, cwd=cwd).returncode == 0


def commits_in_range(from_sha: str, to_sha: str, cwd: Path) -> list[str]:
    """First-parent SHAs in (from_sha, to_sha], oldest-first.

    `--first-parent` follows only the mainline of the PR branch, so a merge
    from base appears as a single commit (its second-parent's history is
    attributed to the merge itself). Without this we'd see commits that
    were already on the base branch as separate non-trivial nodes.
    """
    output = _git_ok("rev-list", "--reverse", "--first-parent", f"{from_sha}..{to_sha}", cwd=cwd)
    return [s for s in output.strip().splitlines() if s]


def commit_parents(sha: str, cwd: Path) -> list[str]:
    output = _git_ok("rev-list", "--parents", "-n", "1", sha, cwd=cwd)
    return output.strip().split()[1:]


def is_clean_merge_from_base(sha: str, cwd: Path, base_ref: str) -> bool:
    """True if `sha` is a merge whose foreign parents are all in base history
    AND whose combined-condensed diff is empty (no manual conflict edits).

    `--diff-merges=cc` shows only hunks that differ from ALL parents — i.e.,
    manual conflict-resolution. Empty means the merge brought in parent
    content verbatim. Restricting the foreign parents to the base ref's
    ancestry rejects merges from arbitrary branches that haven't passed
    base-branch review.
    """
    parents = commit_parents(sha, cwd)
    if len(parents) < 2:
        return False
    cc_output = _git_ok("show", sha, "--diff-merges=cc", "--format=", "-p", cwd=cwd)
    if cc_output.strip():
        return False
    for foreign_parent in parents[1:]:
        if not is_ancestor(foreign_parent, base_ref, cwd):
            return False
    return True


def files_in_commit(sha: str, cwd: Path) -> list[str]:
    output = _git_ok("diff-tree", "--no-commit-id", "--name-only", "-r", sha, cwd=cwd)
    return [p for p in output.strip().splitlines() if p]


def classify_commit(sha: str, cwd: Path, base_ref: str) -> str:
    """Classify a commit as 'merge', 'trivial', or 'non_trivial'."""
    if len(commit_parents(sha, cwd)) >= 2:
        return "merge" if is_clean_merge_from_base(sha, cwd, base_ref) else "non_trivial"
    files = files_in_commit(sha, cwd)
    if not files:
        return "trivial"
    return "trivial" if all(is_trivial_at_dismiss_time(f) for f in files) else "non_trivial"


# ── Decision ─────────────────────────────────────────────────────


def evaluate_delta(last_approved_sha: str, head_sha: str, cwd: Path, base_ref: str = "origin/master") -> dict:
    """Pure decision logic over a local git repo. Network-free.

    `base_ref` is the ref a merge must be reachable from to be trusted as
    "from base branch" (default `origin/master`; tests pass `master`).
    """
    if not is_ancestor(last_approved_sha, head_sha, cwd):
        return {"action": "dismiss", "reason": "non_linear_history"}

    commits = commits_in_range(last_approved_sha, head_sha, cwd)
    if not commits:
        return {"action": "retain", "reason": "empty_delta", "commits_count": 0}

    classifications = [classify_commit(c, cwd, base_ref) for c in commits]
    if any(c == "non_trivial" for c in classifications):
        return {
            "action": "dismiss",
            "reason": "non_trivial_delta",
            "commits_count": len(commits),
            "non_trivial_commits": sum(1 for c in classifications if c == "non_trivial"),
        }

    has_merge = any(c == "merge" for c in classifications)
    has_trivial = any(c == "trivial" for c in classifications)
    if has_merge and has_trivial:
        reason = "mixed_trivial"
    elif has_merge:
        reason = "merge_only"
    else:
        reason = "trivial_paths"
    return {"action": "retain", "reason": reason, "commits_count": len(commits)}


def decide(repo: str, pr_number: int, head_sha: str, cwd: Path, base_ref: str = "origin/master") -> dict:
    last_approved_sha = find_last_approved_sha(repo, pr_number)
    if last_approved_sha is None:
        return {"action": "dismiss", "reason": "no_prior_approval", "last_approved_sha": None}
    decision = evaluate_delta(last_approved_sha, head_sha, cwd, base_ref)
    decision["last_approved_sha"] = last_approved_sha
    return decision


# ── Output / telemetry ───────────────────────────────────────────


def _capture(decision: dict, repo: str, pr_number: int, pr_author: str) -> None:
    if not _POSTHOG_AVAILABLE:
        return
    posthoganalytics.capture(
        distinct_id=pr_author or "unknown",
        event="stamphog_dismiss_decision",
        properties={
            "ai_product": "stamphog",
            "stamphog_action": decision.get("action", ""),
            "stamphog_reason": decision.get("reason", ""),
            "stamphog_last_approved_sha": decision.get("last_approved_sha") or "",
            "stamphog_commits_count": decision.get("commits_count", 0),
            "stamphog_non_trivial_commits": decision.get("non_trivial_commits", 0),
            "stamphog_pr_number": pr_number,
            "stamphog_repo": repo,
        },
    )
    posthoganalytics.flush()


# ── CLI ──────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Stamphog dismissal decider")
    parser.add_argument("--repo", default=os.environ.get("REPO", "PostHog/posthog"))
    parser.add_argument("--pr", type=int, default=int(os.environ.get("PR_NUMBER", "0") or "0"))
    parser.add_argument("--head-sha", default=os.environ.get("HEAD_SHA", ""))
    parser.add_argument("--base-ref", default=os.environ.get("BASE_REF", "origin/master"))
    parser.add_argument("--cwd", default=os.environ.get("GITHUB_WORKSPACE") or ".")
    args = parser.parse_args()

    pr_author = os.environ.get("PR_AUTHOR", "")

    if not args.pr or not args.head_sha:
        decision = {
            "action": "dismiss",
            "reason": "missing_input",
            "last_approved_sha": None,
        }
        print(json.dumps(decision))
        _capture(decision, args.repo, args.pr, pr_author)
        sys.exit(0)

    cwd = Path(args.cwd).resolve()

    try:
        decision = decide(args.repo, args.pr, args.head_sha, cwd, args.base_ref)
    except Exception as e:
        decision = {
            "action": "dismiss",
            "reason": f"error:{type(e).__name__}",
            "last_approved_sha": None,
            "error_message": str(e)[:200],
        }

    print(json.dumps(decision))
    _capture(decision, args.repo, args.pr, pr_author)


if __name__ == "__main__":
    main()
