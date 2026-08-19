"""Decide whether a push leaves a standing stamphog approval in place.

GitHub never auto-dismisses an approval, so the review workflow retracts stamphog's before every
re-review. That is correct for a push that changes code, and wrong for the push that dominates a
long-lived PR: a merge of the base branch, which leaves the PR's own diff alone. It drops the PR out
of merge readiness and spends a full sandboxed LLM review to re-derive the verdict it already had.

Retention answers exactly one question: is what stamphog approved byte-identical to what is there
now? It compares the PR's own diff at the approved head against the current head, keyed on each
changed file's blob sha, so it never has to judge whether a given file matters. A merge of the base
branch that touches none of the PR's files leaves every blob identical and retains; a merge that has
to resolve a conflict inside one of them changes that blob and re-reviews.

Both sides come from `compare_commits`, which takes two commit shas. That is load-bearing rather
than incidental: `get_pr_files` answers for whichever head is live when the request runs, so a
contributor could push the approved content, let the comparison run, and push the unreviewed head
back. Reading two immutable commits leaves no such window.

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

from collections.abc import Sequence

# Heads a run's approval covers beyond the one it was posted at. The merge handler matches an
# approving run on head_sha alone, so a retained PR would otherwise merge as unapproved.
RETAINED_HEADS_KEY = "retained_head_shas"

# Bounds the list on a PR that takes many base-branch merges. Only the recent heads can still be the
# merged one, so dropping the oldest costs nothing.
MAX_RETAINED_HEADS = 50

# The single reason an approval survives a push, recorded in the webhook skip log.
UNCHANGED_DIFF = "unchanged_diff"


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


def approved_diff_unchanged(
    approved_files: Sequence[dict],
    current_files: Sequence[dict],
    *,
    max_files: int,
) -> bool:
    """Whether the PR's own diff is byte-identical to the one that was approved.

    False for everything ambiguous. An approval is only ever retained on positive evidence that not
    one blob in the PR's diff moved.
    """
    approved = diff_fingerprint(approved_files, max_files=max_files)
    current = diff_fingerprint(current_files, max_files=max_files)
    if approved is None or current is None:
        return False
    return approved == current
