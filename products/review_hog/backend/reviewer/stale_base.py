"""Stale-base detection for stacked pull requests.

When a pull request targets a non-default branch (`base_branch != default_branch`), a restack or
base-branch force-push can briefly leave `base_branch...head_sha` contaminated with commits the pull
request did not author:

1. `base_behind_default`: `head_sha` was rebased onto (or merged) a newer commit of `default_branch`
   than `base_branch` contains. Let `M_head = merge_base(default_branch, head_sha)`. If
   `compare(base_ref...M_head).ahead_by > 0`, `M_head` is not an ancestor of `base_branch`, so
   `base_branch...head_sha` is guaranteed to include unrelated `default_branch` commits.
2. `base_rewritten`: `base_branch` was amended or force-pushed while `head_sha` still sits on the
   old commits of `base_branch`. Then `merge_base(base_ref, head_sha) == M_head` while
   `compare(base_ref...head_sha).behind_by > 0` (they share no stack history above `default_branch`).
   To avoid false positives on independent PRs branched from `default_branch` targeting a long-lived
   release/integration branch, this triggers only when non-merge, non-trivial commit subjects in
   `default_branch...base_ref` also appear in `base_ref...head_sha`.

Every failure fails open (`unavailable`), so GitHub hiccups never block a review. PRs targeting
`default_branch` return `default_base` immediately with zero extra API calls.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import requests

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError

from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError, github_api_request

logger = logging.getLogger(__name__)

# Switch off to observe stale-base skips in shadow mode (`stale=True, skip=False`) before gating.
SKIP_STALE_BASE = True

# GitHub's compare endpoint pages its commit list at this size.
_COMPARE_COMMITS_PER_PAGE = 100

# Short or generic subjects can collide across unrelated PRs, so `base_rewritten` ignores them.
_MIN_SUBJECT_CHARS = 12
_TRIVIAL_SUBJECTS = frozenset({"wip", "fix", "fixes", "cleanup", "lint", "nit", "nits", "typo", "update", "temp"})

StaleBaseReason = Literal[
    "default_base",
    "clean_stack",
    "base_behind_default",
    "base_rewritten",
    "unavailable",
]


@frozen
class StaleBaseDecision:
    """Whether a stacked pull request's `base...head` diff is contaminated by stale base history."""

    stale: bool
    skip: bool
    reason: StaleBaseReason
    # For `base_behind_default`: how many `default_branch` commits sit ahead of `base_branch` inside `head_sha`.
    default_commits_in_diff: int | None = None
    # For `base_rewritten`: how many non-trivial commit subjects from `default...base` reappear in `base...head`.
    overlapping_base_commits: int | None = None


def _normalized_subject(commit: Mapping[str, Any]) -> str | None:
    """First line of a non-merge commit message, normalized, or None if merge/trivial."""
    parents = commit.get("parents") or []
    if len(parents) > 1:
        return None
    message = ((commit.get("commit") or {}).get("message") or "").strip()
    if not message:
        return None
    subject = " ".join(message.splitlines()[0].strip().lower().split())
    if not subject or subject.startswith("merge ") or subject in _TRIVIAL_SUBJECTS or len(subject) < _MIN_SUBJECT_CHARS:
        return None
    return subject


def commit_subjects(commits: Sequence[Mapping[str, Any]]) -> set[str]:
    """Non-merge, non-trivial commit subjects from a GitHub compare payload's `commits` list."""
    subjects: set[str] = set()
    for commit in commits:
        subject = _normalized_subject(commit)
        if subject is not None:
            subjects.add(subject)
    return subjects


def _merge_base_sha(comparison: Mapping[str, Any]) -> str | None:
    sha = (comparison.get("merge_base_commit") or {}).get("sha")
    return sha if isinstance(sha, str) and sha else None


def is_pr_stale_for_publish(
    *,
    live_state: str | None,
    live_base_branch: str | None,
    reviewed_base_branch: str | None,
) -> str | None:
    """Whether a live PR moved into a state where publishing the reviewed diff would post stale comments.

    Returns a short reason (`"pr_not_open"` or `"base_branch_changed"`), or None when safe to publish.
    A normal push on the same base branch stays publishable (inline comments pin to `head_sha`).
    """
    if live_state is not None and live_state != "open":
        return "pr_not_open"
    if reviewed_base_branch and live_base_branch and live_base_branch != reviewed_base_branch:
        return "base_branch_changed"
    return None


class StaleBaseChecker:
    def __init__(self, *, repository: str, token: str, installation_id: str | None) -> None:
        self.repository = repository
        self._token = token
        self._installation_id = installation_id

    def _compare(self, base: str, head: str, *, per_page: int = 1) -> dict[str, Any] | None:
        try:
            return github_api_request(
                "GET",
                f"/repos/{self.repository}/compare/{base}...{head}",
                token=self._token,
                installation_id=self._installation_id,
                endpoint="/repos/{owner}/{repo}/compare/{basehead}",
                params={"per_page": per_page},
            ).json()
        except (GitHubAPIError, GitHubRateLimitError, requests.RequestException) as error:
            logger.warning(
                "Stale-base check could not compare %s...%s in %s: %s",
                base,
                head,
                self.repository,
                type(error).__name__,
            )
            return None

    def check(
        self,
        *,
        default_branch: str | None,
        base_branch: str | None,
        head_sha: str | None,
        base_sha: str | None = None,
        merge_base_sha: str | None = None,
        base_behind_by: int | None = None,
    ) -> StaleBaseDecision:
        """Check whether a stacked PR's diff against `base_branch` is contaminated.

        `base_sha`, `merge_base_sha`, and `base_behind_by` avoid redundant GitHub reads when the
        caller already fetched the PR metadata and `compare(base_branch...head_sha)`.
        """
        if not default_branch or not base_branch or not head_sha or base_branch == default_branch:
            return StaleBaseDecision(stale=False, skip=False, reason="default_base")

        # Pin to the exact base commit GitHub diffed against when available; fall back to branch name.
        base_ref = base_sha or base_branch

        head_vs_default = self._compare(default_branch, head_sha, per_page=1)
        if head_vs_default is None:
            return StaleBaseDecision(stale=False, skip=False, reason="unavailable")
        head_default_merge_base = _merge_base_sha(head_vs_default)
        if head_default_merge_base is None:
            return StaleBaseDecision(stale=False, skip=False, reason="unavailable")

        # Check 1: Does `head_sha` include `default_branch` commits that `base_branch` does not?
        default_vs_base = self._compare(base_ref, head_default_merge_base, per_page=1)
        if default_vs_base is None:
            return StaleBaseDecision(stale=False, skip=False, reason="unavailable")
        default_commits_ahead = int(default_vs_base.get("ahead_by") or 0)
        if default_commits_ahead > 0:
            return StaleBaseDecision(
                stale=True,
                skip=SKIP_STALE_BASE,
                reason="base_behind_default",
                default_commits_in_diff=default_commits_ahead,
            )

        # Check 2: Was `base_branch` rewritten/force-pushed so `head_sha` shares no stack commits with it?
        base_vs_head: dict[str, Any] | None = None
        if merge_base_sha is None or base_behind_by is None:
            base_vs_head = self._compare(base_ref, head_sha, per_page=_COMPARE_COMMITS_PER_PAGE)
            if base_vs_head is None:
                return StaleBaseDecision(stale=False, skip=False, reason="unavailable")
            merge_base_sha = _merge_base_sha(base_vs_head)
            base_behind_by = int(base_vs_head.get("behind_by") or 0)

        if merge_base_sha != head_default_merge_base or base_behind_by <= 0:
            return StaleBaseDecision(stale=False, skip=False, reason="clean_stack")

        # `base_branch` and `head_sha` diverged at `default_branch` with `base_branch` holding its own commits.
        # Confirm overlap against `default_branch...base_ref` commits so independent PRs targeting a long-lived
        # release branch are never treated as stale.
        if base_vs_head is None or "commits" not in base_vs_head:
            base_vs_head = self._compare(base_ref, head_sha, per_page=_COMPARE_COMMITS_PER_PAGE)
            if base_vs_head is None:
                return StaleBaseDecision(stale=False, skip=False, reason="unavailable")
        base_vs_default = self._compare(default_branch, base_ref, per_page=_COMPARE_COMMITS_PER_PAGE)
        if base_vs_default is None:
            return StaleBaseDecision(stale=False, skip=False, reason="unavailable")

        head_subjects = commit_subjects(base_vs_head.get("commits") or [])
        base_subjects = commit_subjects(base_vs_default.get("commits") or [])
        overlap = head_subjects & base_subjects
        if overlap:
            return StaleBaseDecision(
                stale=True,
                skip=SKIP_STALE_BASE,
                reason="base_rewritten",
                overlapping_base_commits=len(overlap),
            )

        return StaleBaseDecision(stale=False, skip=False, reason="clean_stack")
