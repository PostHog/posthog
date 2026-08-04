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

A queue that batched several PRs onto one gate branch would break the one-PR assumption. Neither
shape above does — batching would need a new shape here, not a new rule at each call site.
"""

# Branch-name prefixes a merge queue pushes its gate branches under.
MERGE_QUEUE_BRANCH_PREFIXES: tuple[str, ...] = ("trunk-merge/", "gh-readonly-queue/")

# Both shapes carry the source PR as a ``pr-<number>`` segment; the trailing separator ('/' before
# Trunk's uuid, '-' before GitHub's sha) is what ends the digit run. ``[0-9]`` rather than ``\d``
# keeps the pattern backslash-free, so it survives embedding in a HogQL string literal unescaped.
_SOURCE_PR_PATTERN = "^(?:trunk-merge/|gh-readonly-queue/[^/]+/)pr-([0-9]+)[/-]"


# Every expression below guards its input with ``ifNull``. A branch column can read NULL rather than
# '' — the CI spans hold theirs in a map, which yields NULL for a run that predates the stamp — and a
# NULL into startsWith/regexpExtract makes the whole expression NULL. That is not a cosmetic
# difference: `WHERE NOT <NULL>` drops the row, and `if(<NULL> != '', a, b)` returns NULL instead of
# the fallback, so an unstamped branch would silently delete data rather than fail a filter.
def _branch(column: str) -> str:
    return f"ifNull({column}, '')"


def merge_queue_branch_expr(column: str) -> str:
    """HogQL predicate: does ``column`` hold a merge-queue gate branch?"""
    return (
        "(" + " OR ".join(f"startsWith({_branch(column)}, '{prefix}')" for prefix in MERGE_QUEUE_BRANCH_PREFIXES) + ")"
    )


def source_pr_string_expr(column: str) -> str:
    """HogQL: the PR number a gate branch is landing, as a string; '' when it is not a gate branch.

    The string flavor exists for the CI-span reads, where ``pr_number`` is a resource attribute
    (a String) and '' is already that layer's "unattributed" sentinel.
    """
    return f"regexpExtract({_branch(column)}, '{_SOURCE_PR_PATTERN}')"


def source_pr_number_expr(column: str) -> str:
    """HogQL: the PR number a gate branch is landing, 0 when ``column`` holds no gate branch.

    0 rather than NULL to match the runs builder's existing "no attribution" sentinel for
    ``pr_number``, so the two compose with a plain comparison instead of a null-guard.
    """
    return f"ifNull(accurateCastOrNull({source_pr_string_expr(column)}, 'Int64'), 0)"
