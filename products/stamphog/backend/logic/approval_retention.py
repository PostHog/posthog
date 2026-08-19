"""Decide whether a push leaves a standing stamphog approval in place.

GitHub never auto-dismisses an approval, so the review workflow retracts stamphog's before every
re-review. That is right for a push that changes code, and wrong for the one that dominates a
long-lived PR: a merge of the base branch, which leaves the PR's own diff alone and still costs the
PR its merge readiness plus a full sandboxed review to re-derive the verdict it had.

So retention answers one question, and never judges whether a given file matters: is the PR's own
diff byte-identical to the one that was approved?

Three properties of that comparison are load-bearing, each earned from a review finding:

- Both sides come from `compare_diff` on two commit shas. `get_pr_files` answers for whichever head
  is live when the request runs, which a contributor can move under it.
- It compares diff text, not per-file blob shas. The text carries file modes and renames; a blob sha
  covers contents only, and GitHub's file payload has no mode at all.
- Anything it cannot actually see is refused rather than compared. See the guards in
  `approved_diff_unchanged`.

Resist adding a "this file is harmless" allowlist back. One existed and every entry in it turned out
to be executable somewhere in this repository, down to plain Markdown, which ships through
`services/mcp` templates and product `tools.yaml` prompts.
"""

from __future__ import annotations

import re

# Heads a run's approval covers beyond the one it was posted at. The merge handler matches an
# approving run on head_sha alone, so a retained PR would otherwise merge as unapproved.
RETAINED_HEADS_KEY = "retained_head_shas"

# Bounds the list on a PR that takes many base-branch merges. Only the recent heads can still be the
# merged one, so dropping the oldest costs nothing.
MAX_RETAINED_HEADS = 50

# The single reason an approval survives a push, recorded in the webhook skip log.
UNCHANGED_DIFF = "unchanged_diff"


# git renders a binary change as this line over an abbreviated blob id, never as content. Two
# different binaries whose ids share that prefix produce the same line, and grinding a padding
# section until they do is within reach, so a diff carrying one cannot answer the question.
_BINARY_MARKER_RE = re.compile(r"^Binary files\b.*differ$", re.MULTILINE)


def approved_diff_unchanged(approved_diff: str, current_diff: str) -> bool:
    """Whether the PR's own diff is byte-identical to the one that was approved.

    False for everything ambiguous. An empty diff on either side counts as ambiguous rather than as
    "nothing changed": a PR with no changes at all is degenerate, and treating the two as equal would
    retain an approval on the strength of two blanks. A diff describing a binary change is refused
    for a sharper reason, see _BINARY_MARKER_RE.
    """
    if not approved_diff.strip() or not current_diff.strip():
        return False
    if _BINARY_MARKER_RE.search(approved_diff) or _BINARY_MARKER_RE.search(current_diff):
        return False
    return approved_diff == current_diff
