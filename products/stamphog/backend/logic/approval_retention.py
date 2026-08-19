"""Decide whether a push leaves a standing stamphog approval in place.

GitHub never auto-dismisses an approval, so the review workflow retracts stamphog's before every
re-review. That is correct for a push that changes code, and wrong for the push that dominates a
long-lived PR: a merge of the base branch, which leaves the PR's own diff alone. It drops the PR out
of merge readiness and spends a full sandboxed LLM review to re-derive the verdict it already had.

Retention answers exactly one question: is what stamphog approved byte-identical to what is there
now? It compares the PR's own unified diff at the approved head against the same at the current
head, so it never has to judge whether a given file matters. A merge of the base branch that touches
none of the PR's files produces the identical diff and retains; a merge that has to resolve a
conflict inside one of them changes it and re-reviews.

Comparing the diff text rather than a per-file blob sha is deliberate. The text carries everything
git records about a change, file modes and renames included, so flipping the executable bit on a
file the PR already edits moves it. A blob sha covers contents only, and nothing in GitHub's file
payload carries the mode.

The one thing the text does not carry is binary content, which git renders as "Binary files ...
differ" over an abbreviated blob id. Two different binaries whose ids share that short prefix would
read as identical, so a diff mentioning one is refused rather than compared.

Both sides come from `compare_diff`, which takes two commit shas. That is load-bearing too:
`get_pr_files` answers for whichever head is live when the request runs, so a contributor could push
the approved content, let the comparison run, and push the unreviewed head back. Reading two
immutable commits leaves no such window.

There is deliberately no "this file is harmless" rule. Successive review passes found that every
candidate for one was wrong in this repository: lockfiles select the dependency code that gets
installed, tests run in CI with CI's credentials, a file under a generated/ directory can be
hand-edited and still compiles into a service, docs/onboarding is aliased into the production
frontend, MDX compiles to JavaScript, snapshot files are JavaScript modules the test runner
executes, and even plain Markdown ships, because services/mcp imports .md templates and product
tools.yaml files compile .md prompts into shipped tool definitions. Retention has no human in the
loop, so it makes no judgment calls at all.
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
