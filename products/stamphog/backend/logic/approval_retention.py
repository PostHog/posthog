"""Decide whether a push is trivial enough to leave a standing stamphog approval in place.

GitHub never auto-dismisses an approval, so the review workflow retracts stamphog's before every
re-review. That is correct for a push that changes code, and wrong for the two pushes that dominate a
long-lived PR: a docs or test touch-up, and a merge of the base branch that leaves the PR's own diff
alone. Both drop the PR out of merge readiness and spend a full sandboxed LLM review to re-derive the
verdict the PR already had.

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

# Ecosystems whose lockfile is the sole record of what actually gets installed, so a lockfile-only
# push carries no reviewable code. go.sum is absent on purpose: it hashes what go.mod names rather
# than naming the dependencies itself.
_TRUSTED_LOCKFILES = frozenset(
    {
        "pnpm-lock.yaml",
        "package-lock.json",
        "yarn.lock",
        "npm-shrinkwrap.json",
        "uv.lock",
        "poetry.lock",
        "pipfile.lock",
        "gemfile.lock",
        "composer.lock",
        "cargo.lock",
    }
)

_TRIVIAL_EXTENSIONS = frozenset({".md", ".mdx"})
_TRIVIAL_NAME_PREFIXES = ("readme", "changelog")

_TEST_RE = re.compile(
    r"(?:^|/)(?:__tests__|tests?|fixtures)/|(?:^|/)test_[^/]+\.py$|_test\.(py|go)$"
    r"|\.test\.(ts|tsx|js|jsx)$|\.spec\.(ts|tsx|js|jsx)$|(?:^|/)conftest\.py$",
    re.IGNORECASE,
)
_GENERATED_RE = re.compile(
    r"(?:^|/)generated/.*\.(ts|tsx|js|jsx|json|md|snap|pyi|txt)$"
    r"|\.gen\.(ts|tsx|js|jsx)$|\.generated\.(ts|tsx|js|jsx)$",
    re.IGNORECASE,
)

# Stamphog's own policy and engine files are never trivial, or a retained approval would let an edit
# to the gate itself land unreviewed. AGENT_APPROVALS.md is the one that makes this necessary rather
# than merely tidy: it is markdown, which every other rule here treats as blanket-trivial.
_GATE_OWN_FILES_RE = re.compile(r"\.stamphog/|AGENT_APPROVALS\.md|tools/pr-approval-agent/|CODEOWNERS", re.IGNORECASE)


class RetentionReason(StrEnum):
    """Why a standing approval survived a push. Recorded on the PR and in the skip log."""

    UNCHANGED_DIFF = "unchanged_diff"
    TRIVIAL_PATHS = "trivial_paths"


def is_trivial_at_dismiss_time(path: str) -> bool:
    """Whether this path alone is safe enough to retain a standing approval.

    Deliberately narrower than the engine's approve-time allowlist. At approve time an LLM reads the
    diff as well; here the path is the only signal, so anything that can execute or alter build and CI
    behavior stays out: `.github/**`, bare `*.yaml` and `*.json` config, `Dockerfile*`, `*.sh`,
    `Makefile`.
    """
    if _GATE_OWN_FILES_RE.search(path):
        return False

    name = Path(path).name.lower()
    if name in _TRUSTED_LOCKFILES:
        return True
    if Path(path).suffix.lower() in _TRIVIAL_EXTENSIONS:
        return True
    if name.startswith(_TRIVIAL_NAME_PREFIXES):
        return True
    if path.startswith("docs/") or "/docs/" in path:
        return True
    if "/__snapshots__/" in path or path.startswith("__snapshots__/"):
        return True
    return bool(_TEST_RE.search(path) or _GENERATED_RE.search(path))


def diff_fingerprint(files: Sequence[dict]) -> dict[str, str] | None:
    """Map each changed file to its blob sha, or None when the payload can't be trusted.

    None means "cannot answer", never "nothing changed": a file object without a sha would otherwise
    compare equal to another missing one and retain an approval over a diff nobody checked.
    """
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
) -> RetentionReason | None:
    """The reason to retain the standing approval, or None to dismiss it and re-review.

    Everything ambiguous returns None. A push is only ever retained on positive evidence that what
    stamphog approved is unchanged, or that every file whose content moved is one the path rules call
    trivial on its own.
    """
    approved = diff_fingerprint(approved_files)
    current = diff_fingerprint(current_files)
    if approved is None or current is None:
        return None

    changed_paths = {path for path in approved.keys() | current.keys() if approved.get(path) != current.get(path)}
    if not changed_paths:
        return RetentionReason.UNCHANGED_DIFF
    if all(is_trivial_at_dismiss_time(path) for path in changed_paths):
        return RetentionReason.TRIVIAL_PATHS
    return None
