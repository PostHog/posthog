"""Merge-queue branches: telling a CI gate artifact apart from real work.

A merge queue lands a pull request by pushing a throwaway branch carrying that PR's commits
rebased onto the current default branch, running the full suite there, and merging only if it
stays green. GitHub sees the gate branch as an ordinary pull request, so the warehouse snapshot
gains one extra draft PR per merge attempt and one extra full CI fan-out — associated to *that*
PR, not the one being landed.

Left alone, every PR surface counts gate artifacts as work: the attention list fills with bot
drafts that no human can act on, the open-PR and failing-CI cards over-count, and a PR's cost
card omits the gate run its own merge paid for. This module is where the product knows the
difference, defined once (SPEC §3).

Two shapes are recognized, both of which name their source PR in the branch:

- Trunk: ``trunk-merge/pr-<number>/<uuid>``, and the ``-bisection`` suffix variant Trunk pushes
  while bisecting a flaky failure.
- GitHub's native queue: ``gh-readonly-queue/<base-branch>/pr-<number>-<sha>``.

The branch name is the attribution key on purpose. It is immutable for the branch's life and
names exactly one PR, so it carries none of the ambiguity SPEC §6 bans the head-SHA join for: a
gate branch's head SHA is a rebase that exists nowhere else, and its own ``pull_requests``
association points at the throwaway PR rather than the real one.

**The shape alone is not enough, because branch names are contributor-controlled.** On a public
repo anyone can open a PR from a branch called ``trunk-merge/pr-123/anything``; on the shape alone
we would drop their PR from every surface and re-key its runs, jobs and cost onto PR 123. So every
destructive use pairs the shape with an identity the pusher cannot set: GitHub stamps ``actor`` on
a run and ``user`` on a PR, and a real gate artifact carries a queue bot in both. Measured over two
months of ``PostHog/posthog``: 51,052 gate-shaped runs, all with ``actor`` = ``trunk-io[bot]``, none
from a fork — so requiring it costs nothing today and closes the spoof.

A queue that batched several PRs onto one gate branch would break the one-PR assumption. Neither
shape above does — batching would need a new shape here, not a new rule at each call site.
"""

# Both shapes carry the source PR as a ``pr-<number>`` segment; the trailing separator ('/' before
# Trunk's uuid, '-' before GitHub's sha) is what ends the digit run. ``[0-9]`` rather than ``\d``
# keeps the pattern backslash-free, so it survives embedding in a HogQL string literal unescaped.
_SOURCE_PR_PATTERN = "^(?:trunk-merge/|gh-readonly-queue/[^/]+/)pr-([0-9]+)[/-]"

# The identities a real merge queue acts as. GitHub's native queue pushes gate branches without
# opening a PR, so only Trunk needs an entry today.
MERGE_QUEUE_BOT_HANDLES: frozenset[str] = frozenset({"trunk-io[bot]"})


# Both helpers ``ifNull`` their input, and that is load-bearing rather than defensive: a branch or
# actor column can read NULL rather than '' (the CI spans hold theirs in a map, NULL for a run that
# predates the stamp), and NULL into regexpExtract poisons the whole expression. `WHERE NOT <NULL>`
# drops the row and `if(<NULL>, a, b)` returns NULL instead of the fallback, so an unstamped column
# would silently delete data rather than fail a filter.
def _source_pr_string(branch_column: str) -> str:
    return f"regexpExtract(ifNull({branch_column}, ''), '{_SOURCE_PR_PATTERN}')"


def _pushed_by_queue(actor_column: str) -> str:
    handles = ", ".join(f"'{handle}'" for handle in sorted(MERGE_QUEUE_BOT_HANDLES))
    return f"ifNull({actor_column}, '') IN ({handles})"


def looks_like_merge_queue_branch_expr(branch_column: str) -> str:
    """HogQL predicate on the branch **shape alone** — no identity corroboration.

    Only for reads where a false positive cannot drop or re-key anything, i.e. where the worst case
    is one miscounted row. The failure-lines view (Logs) carries no actor to corroborate against, and
    its gate-branch count only feeds a classifier verdict, so it uses this. Anything that decides
    what a row *is* must use ``merge_queue_branch_expr`` instead — see the module docstring on why
    the shape is contributor-controlled.
    """
    return f"{_source_pr_string(branch_column)} != ''"


def source_pr_string_expr(branch_column: str, *, queue_actor_column: str) -> str:
    """HogQL: the PR number a corroborated gate branch is landing, as a string; '' otherwise.

    The string flavor exists for the CI-span reads, where ``pr_number`` is a resource attribute
    (a String) and '' is already that layer's "unattributed" sentinel.

    ``queue_actor_column`` is required, not optional, so no caller can take the branch name's word
    for it: the identity that owns the artifact (a run's ``actor``, a PR's ``user``, a span's
    ``ci.actor``). A non-queue identity yields '' — the same "not a gate branch" answer as a
    non-matching name.
    """
    return f"if({_pushed_by_queue(queue_actor_column)}, {_source_pr_string(branch_column)}, '')"


def source_pr_number_expr(branch_column: str, *, queue_actor_column: str) -> str:
    """HogQL: the PR number a corroborated gate branch is landing, 0 otherwise.

    0 rather than NULL to match the runs builder's existing "no attribution" sentinel for
    ``pr_number``, so the two compose with a plain comparison instead of a null-guard.
    """
    string_expr = source_pr_string_expr(branch_column, queue_actor_column=queue_actor_column)
    return f"ifNull(accurateCastOrNull({string_expr}, 'Int64'), 0)"


def merge_queue_branch_expr(branch_column: str, *, queue_actor_column: str) -> str:
    """HogQL predicate: is this a merge-queue gate branch, pushed by the queue?

    Defined as "we resolved a source PR from it" rather than a cheaper prefix test, so recognizing a
    gate branch and attributing one can never disagree. A prefix test would classify a branch the
    pattern cannot resolve (a queue shape we don't know yet, a base branch containing a slash), and
    that disagreement is destructive in one direction: the PR row is dropped from the curated source
    while its runs keep pointing at it. Failing to recognize an exotic shape only leaves us the
    cleanup we have today; misrecognizing one loses data.
    """
    return f"{source_pr_number_expr(branch_column, queue_actor_column=queue_actor_column)} > 0"


def gate_attempt_expr(branch_column: str) -> str:
    """HogQL expression naming the gate attempt a run belongs to: the gate branch with Trunk's
    ``-bisection`` suffix collapsed, so a flake-bisection probe groups with the attempt it
    investigates instead of counting as an attempt of its own."""
    return f"replaceRegexpOne({branch_column}, '-bisection$', '')"
