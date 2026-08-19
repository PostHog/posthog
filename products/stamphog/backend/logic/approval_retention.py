"""Decide whether a push is trivial enough to leave a standing stamphog approval in place.

GitHub never auto-dismisses an approval, so the review workflow retracts stamphog's before every
re-review. That is correct for a push that changes code, and wrong for the two pushes that dominate a
long-lived PR: a merge of the base branch that leaves the PR's own diff alone, and a documentation
touch-up. Both drop the PR out of merge readiness and spend a full sandboxed LLM review to re-derive
the verdict the PR already had.

The decision is content-based rather than commit-based. It compares the PR's own diff at the approved
head against the current head, keyed on each changed file's blob sha as GitHub reports it, so the
question is "did what stamphog approved change?" rather than "which commits landed?". A merge of the
base branch that touches none of the PR's files leaves every blob identical and retains the approval;
a merge that has to resolve a conflict inside one of them changes that blob and re-reviews. That makes
it at least as strict as walking the commits: any edit smuggled in as conflict resolution shows up as
a changed blob, which the engine's commit walk could only catch by diffing the merge itself.

These rules are server-owned and deliberately NOT read from the reviewed repo's `.stamphog/policy.yml`.
The engine's approve-time policy is repo-overridable because a human still reviews whatever it lets
through. This one has no such backstop: a repo able to widen it would add its own source extensions
and keep an approval standing across arbitrary code pushes.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path

# Suffixes whose content cannot execute anywhere: not in CI, not in a build, not in a shipped
# artifact. The list is deliberately shorter than what the path alone might suggest is safe.
#
# Lockfiles, tests, generated sources and anything under docs/ are all excluded even though a change
# to one is usually harmless. A lockfile selects the dependency code that gets installed, a test runs
# in CI with CI's credentials, a file under a generated/ directory can be hand-edited and still
# compiles into a service, and docs/onboarding is aliased into the production frontend, so a .tsx
# there ships. Retention has no human in the loop, so it only trusts content that cannot run.
_INERT_SUFFIXES = frozenset({".md", ".mdx", ".snap"})

# Stamphog's own policy and engine files are never trivial, or a retained approval would let an edit
# to the gate itself land unreviewed. AGENT_APPROVALS.md is the one that makes this necessary rather
# than merely tidy: it is markdown, which the suffix rule above treats as inert.
_GATE_OWN_FILES_RE = re.compile(
    r"\.stamphog/|AGENT_APPROVALS\.md|pr-approval-agent/|CODEOWNERS",
    re.IGNORECASE,
)


# Heads a run's approval covers beyond the one it was posted at. The merge handler matches an
# approving run on head_sha alone, so a retained PR would otherwise merge as unapproved.
RETAINED_HEADS_KEY = "retained_head_shas"

# Bounds the list on a PR that takes many documentation pushes. Only the recent heads can still be
# the merged one, so dropping the oldest costs nothing.
MAX_RETAINED_HEADS = 50


class RetentionReason(StrEnum):
    """Why a standing approval survived a push. Recorded in the webhook skip log."""

    UNCHANGED_DIFF = "unchanged_diff"
    TRIVIAL_PATHS = "trivial_paths"


def is_trivial_at_dismiss_time(path: str) -> bool:
    """Whether this path alone is safe enough to retain a standing approval.

    Deliberately narrower than the engine's approve-time allowlist. At approve time an LLM reads the
    diff as well; here the path is the only signal and nobody reads anything, so the answer is yes
    only for content that cannot execute in CI, in a build, or in a shipped artifact.
    """
    if _GATE_OWN_FILES_RE.search(path):
        return False
    return Path(path).suffix.lower() in _INERT_SUFFIXES


def diff_fingerprint(files: Sequence[dict], *, max_files: int) -> dict[str, str] | None:
    """Map each changed file to its blob sha, or None when the payload can't be trusted.

    None means "cannot answer", never "nothing changed". A file object without a sha would otherwise
    compare equal to another missing one, and a listing that hit the client's page cap is a prefix of
    the diff rather than the diff, so a change past the cap would be invisible.
    """
    if len(files) >= max_files:
        return None
    fingerprint: dict[str, str] = {}
    for changed in files:
        filename = changed.get("filename")
        sha = changed.get("sha")
        if not isinstance(filename, str) or not isinstance(sha, str) or not filename or not sha:
            return None
        fingerprint[filename] = sha
    return fingerprint


def classify_delta(
    approved_files: Sequence[dict],
    current_files: Sequence[dict],
    *,
    max_files: int,
) -> RetentionReason | None:
    """The reason to retain the standing approval, or None to dismiss it and re-review.

    Everything ambiguous returns None. A push is only ever retained on positive evidence that what
    stamphog approved is unchanged, or that every file whose content moved is one the path rules call
    trivial on its own.
    """
    approved = diff_fingerprint(approved_files, max_files=max_files)
    current = diff_fingerprint(current_files, max_files=max_files)
    if approved is None or current is None:
        return None

    changed_paths = {path for path in approved.keys() | current.keys() if approved.get(path) != current.get(path)}
    if not changed_paths:
        return RetentionReason.UNCHANGED_DIFF
    if all(is_trivial_at_dismiss_time(path) for path in changed_paths):
        return RetentionReason.TRIVIAL_PATHS
    return None
