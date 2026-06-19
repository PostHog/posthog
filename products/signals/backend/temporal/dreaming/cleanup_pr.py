"""Singleton "dreaming cleanup" PR management.

Each dreaming run produces at most ONE consolidated instrumentation/cleanup PR per
repository. The singleton guarantee is enforced via the GitHub label
``dreaming-cleanup``: before opening anything, we list open PRs carrying that label.

- **None found** → open a fresh PR (branch + commit + PR), apply the label.
- **One found** → UPDATE it: refresh its description (resurfacing the latest findings) and
  amend its branch with the newest instrumentation additions. Never open a second one.
- **More than one found** → a prior invariant break (or a human opened one). We treat the
  oldest as canonical, update it, and leave the rest alone (logged), so we still never add
  to the count.

This module reuses the existing :class:`GitHubIntegration` auth/client path (installation
token, retry/backoff, rate-limit handling) — it does not invent a new auth flow. Every
GitHub write goes through the integration's existing methods. All network calls are mocked
in tests; nothing here performs a live write outside an explicit, integration-backed run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from posthog.models.integration import GitHubIntegration

logger = logging.getLogger(__name__)

# The single source of truth for "this is the dreaming cleanup PR". Listing open PRs with
# this label is how we guarantee at most one open at a time.
DREAMING_CLEANUP_LABEL = "dreaming-cleanup"

# Deterministic branch name so re-runs amend the same branch rather than forking a new one.
DREAMING_CLEANUP_BRANCH = "posthog-dreaming/instrumentation-cleanup"

# A stable marker we embed in the PR body so we can recognise our own PR even if the label
# was manually stripped — defense-in-depth against the singleton invariant.
DREAMING_PR_BODY_MARKER = "<!-- posthog-dreaming-cleanup -->"


@dataclass(frozen=True)
class CleanupFileEdit:
    """One file the cleanup PR should add or modify, with its full new content."""

    path: str
    content: str
    commit_message: str


@dataclass(frozen=True)
class CleanupPRResult:
    """Outcome of a singleton cleanup-PR reconcile."""

    action: str  # "created" | "updated" | "noop"
    pr_number: int | None
    pr_url: str | None
    note: str = ""


class CleanupPRError(Exception):
    """A non-recoverable failure while reconciling the cleanup PR."""


def _open_labeled_cleanup_prs(github: GitHubIntegration, repository: str) -> list[dict]:
    """Open PRs carrying the dreaming-cleanup label, oldest first.

    GitHub's list-PRs endpoint doesn't filter by label, so we list open PRs and match on the
    label (via the issues endpoint when the list payload omits labels). To keep the singleton
    guard cheap and robust, we additionally treat any open PR whose body carries our marker as
    one of ours.
    """
    listed = github.list_pull_requests(repository, state="open")
    if not listed.get("success"):
        raise CleanupPRError(f"Failed to list pull requests for {repository}: {listed.get('error')}")

    candidates: list[dict] = []
    for pr in listed.get("pull_requests", []):
        labels = {label for label in pr.get("labels", []) if isinstance(label, str)}
        body = pr.get("body") or ""
        if DREAMING_CLEANUP_LABEL in labels or DREAMING_PR_BODY_MARKER in body:
            candidates.append(pr)

    # Oldest first so the canonical PR is deterministic across runs.
    candidates.sort(key=lambda pr: (pr.get("created_at") or "", pr.get("number") or 0))
    return candidates


def _apply_edits(
    github: GitHubIntegration,
    repository: str,
    branch: str,
    edits: list[CleanupFileEdit],
) -> None:
    for edit in edits:
        result = github.update_file(
            repository=repository,
            file_path=edit.path,
            content=edit.content,
            commit_message=edit.commit_message,
            branch=branch,
        )
        if not result.get("success"):
            raise CleanupPRError(f"Failed to write {edit.path} on {branch}: {result.get('error')}")


def _ensure_branch(github: GitHubIntegration, repository: str, branch: str) -> None:
    """Create the cleanup branch if it doesn't already exist (idempotent)."""
    info = github.get_branch_info(repository, branch)
    if info.get("success") and info.get("exists"):
        return
    created = github.create_branch(repository, branch)
    if not created.get("success"):
        raise CleanupPRError(f"Failed to create branch {branch} on {repository}: {created.get('error')}")


def _add_label(github: GitHubIntegration, repository: str, pr_number: int) -> None:
    """Apply the dreaming-cleanup label. Best-effort: a labeling failure must not duplicate
    the PR (the body marker still identifies it), so we log and continue."""
    add_label = getattr(github, "add_labels_to_issue", None)
    if add_label is None:
        logger.info("dreaming cleanup: integration has no add_labels_to_issue; relying on body marker")
        return
    try:
        add_label(repository, pr_number, [DREAMING_CLEANUP_LABEL])
    except Exception:
        logger.warning(
            "dreaming cleanup: failed to apply label; PR identified by body marker instead",
            extra={"repository": repository, "pr_number": pr_number},
        )


def _update_pr_body(github: GitHubIntegration, repository: str, pr_number: int, body: str) -> None:
    update = getattr(github, "update_pull_request", None)
    if update is None:
        logger.info("dreaming cleanup: integration has no update_pull_request; branch amended, body left as-is")
        return
    result = update(repository, pr_number, body=body)
    if not result.get("success"):
        raise CleanupPRError(f"Failed to update PR #{pr_number} body on {repository}: {result.get('error')}")


def reconcile_cleanup_pr(
    github: GitHubIntegration,
    repository: str,
    *,
    title: str,
    body: str,
    edits: list[CleanupFileEdit],
    branch: str = DREAMING_CLEANUP_BRANCH,
) -> CleanupPRResult:
    """Create-or-update the single dreaming-cleanup PR for ``repository``.

    Enforces the singleton invariant: if an open labelled (or marked) PR exists, it is
    UPDATED — never duplicated. ``body`` is augmented with the body marker so the PR stays
    self-identifying even if the label is stripped.

    Returns a :class:`CleanupPRResult` describing what happened. Raises
    :class:`CleanupPRError` on a hard GitHub failure so the activity's retry policy can act.
    """
    body_with_marker = body if DREAMING_PR_BODY_MARKER in body else f"{DREAMING_PR_BODY_MARKER}\n{body}"

    if not edits:
        # Nothing to add — don't open or touch a PR for an empty cleanup. Findings can still
        # be surfaced via the inbox/briefing path; the PR is reserved for concrete edits.
        return CleanupPRResult(action="noop", pr_number=None, pr_url=None, note="no instrumentation edits to apply")

    existing = _open_labeled_cleanup_prs(github, repository)

    if existing:
        canonical = existing[0]
        pr_number = int(canonical["number"])
        if len(existing) > 1:
            extra = [pr.get("number") for pr in existing[1:]]
            logger.warning(
                "dreaming cleanup: multiple open cleanup PRs found; updating oldest, leaving rest",
                extra={"repository": repository, "canonical": pr_number, "others": extra},
            )
        # Amend the existing branch in place, then resurface the description.
        _apply_edits(github, repository, canonical.get("head_branch") or branch, edits)
        _update_pr_body(github, repository, pr_number, body_with_marker)
        return CleanupPRResult(
            action="updated",
            pr_number=pr_number,
            pr_url=canonical.get("url"),
            note=f"updated existing cleanup PR #{pr_number}",
        )

    # No open cleanup PR — create one from scratch.
    _ensure_branch(github, repository, branch)
    _apply_edits(github, repository, branch, edits)
    created = github.create_pull_request(
        repository=repository,
        title=title,
        body=body_with_marker,
        head_branch=branch,
    )
    if not created.get("success"):
        raise CleanupPRError(f"Failed to open cleanup PR on {repository}: {created.get('error')}")

    pr_number = int(created["pr_number"])
    _add_label(github, repository, pr_number)
    return CleanupPRResult(
        action="created",
        pr_number=pr_number,
        pr_url=created.get("pr_url"),
        note=f"opened cleanup PR #{pr_number}",
    )
