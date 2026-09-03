"""Decide whether a push leaves a standing stamphog approval in place.

GitHub never dismisses an approval automatically. The review workflow therefore retracts
stamphog's approval before every re-review. That is correct for a push that changes code. It is
wrong for the push that dominates a long-lived PR: a merge of the base branch. Such a merge does not
change the PR's own diff, but it still costs the PR its merge readiness. It also forces a full
sandboxed review to derive the same verdict again.

Retention answers one question, and it never judges whether a given file matters. The question is
whether the PR's own diff is byte-identical to the diff that was approved.

Three properties of that comparison are necessary for safety. A review finding caused each one:

- Both sides come from `compare_diff` on two commit shas. `get_pr_files` answers for the head that
  is live when the request runs, and a contributor can move that head.
- The comparison uses diff text, not per-file blob shas. The text carries file modes and renames. A
  blob sha covers contents only, and GitHub's file payload carries no mode.
- The comparison refuses anything that it cannot see. See the guards in `approved_diff_unchanged`.

Do not add an allowlist of harmless files. One existed, and every entry in it was executable
somewhere in this repository. Plain Markdown is executable too, because it ships through
`services/mcp` templates and product `tools.yaml` prompts.
"""

from __future__ import annotations

import re

# Heads that a run's approval covers in addition to the head it was posted at. The merge handler
# matches an approving run on head_sha alone, so without this record a retained PR merges as
# unapproved.
RETAINED_HEADS_KEY = "retained_head_shas"

# Bounds the list on a PR that takes many base-branch merges. Only the recent heads can still be
# the merged head, so the oldest entries are safe to drop.
MAX_RETAINED_HEADS = 50

# The only reason an approval survives a push. The webhook skip log records this value.
UNCHANGED_DIFF = "unchanged_diff"


# git renders a binary change as this line over an abbreviated blob id, and never as content. Two
# different binaries whose ids share that prefix produce the same line. An attacker can pad one
# binary until its id collides, so a diff that carries this line cannot show whether the content
# changed.
_BINARY_MARKER_RE = re.compile(r"^Binary files\b.*differ$", re.MULTILINE)


def approved_diff_unchanged(approved_diff: str, current_diff: str) -> bool:
    """Whether the PR's own diff is byte-identical to the one that was approved.

    Returns False for everything ambiguous. An empty diff on either side counts as ambiguous rather
    than as "nothing changed". A PR with no changes at all is degenerate, and two blanks compare
    equal, so such a comparison would retain an approval on no evidence. A diff that describes a
    binary change is refused for a sharper reason, see _BINARY_MARKER_RE.
    """
    if not approved_diff.strip() or not current_diff.strip():
        return False
    if _BINARY_MARKER_RE.search(approved_diff) or _BINARY_MARKER_RE.search(current_diff):
        return False
    return approved_diff == current_diff
