"""Recognize merge-queue gate branches and resolve the pull request each one lands.

A merge queue lands a pull request by pushing a throwaway branch with that PR's commits rebased
onto the default branch, and running CI there. Trunk also opens a pull request for the branch, so
its runs are associated with that throwaway PR, not the one being landed.

Two branch shapes are recognized, and both name the source PR:

- Trunk: ``trunk-merge/pr-<number>/<uuid>``, with a ``-bisection`` suffix on a bisection probe.
- GitHub's native queue: ``gh-readonly-queue/<base-branch>/pr-<number>-<sha>``.

Contributors control branch names, so the shape alone is not proof. Anyone can open a PR from a
branch named ``trunk-merge/pr-123/anything``. Every use that drops or re-keys a row therefore also
requires the queue bot as the run's ``actor`` or the PR's ``user``, which the pusher cannot set.

A queue that batched several PRs onto one gate branch would break the one-PR assumption, and needs
a new shape here.
"""

from datetime import datetime, timedelta

from posthog.dataclasses import frozen

# ``[0-9]`` and not ``\d``, so the pattern has no backslash to escape inside a HogQL string literal.
_SOURCE_PR_PATTERN = "^(?:trunk-merge/|gh-readonly-queue/[^/]+/)pr-([0-9]+)[/-]"

# GitHub's native queue pushes gate branches without opening a PR, so only Trunk needs an entry.
MERGE_QUEUE_BOT_HANDLES: frozenset[str] = frozenset({"trunk-io[bot]"})

# How far before a merge population's start the gate-run scan reaches. Every gate read must use this
# one bound, or two reads split the same PR's attempts differently.
GATE_RUN_LOOKBACK = timedelta(days=7)


@frozen
class GateAttempt:
    """One merge-queue attempt for a pull request, with bisection probes folded into their parent."""

    attempt: str
    started_at: datetime
    completed_at: datetime | None
    failed: bool


# The ``ifNull`` in both helpers is required. A branch or actor column can be NULL, and a NULL
# predicate drops the row in ``WHERE NOT`` and makes ``if()`` return NULL instead of its fallback.
def _source_pr_string(branch_column: str) -> str:
    return f"regexpExtract(ifNull({branch_column}, ''), '{_SOURCE_PR_PATTERN}')"


def _pushed_by_queue(actor_column: str) -> str:
    handles = ", ".join(f"'{handle}'" for handle in sorted(MERGE_QUEUE_BOT_HANDLES))
    return f"ifNull({actor_column}, '') IN ({handles})"


def looks_like_merge_queue_branch_expr(branch_column: str) -> str:
    """HogQL predicate on the branch shape alone, with no check of who pushed it.

    Only for a read where a false positive miscounts one row and cannot drop or re-key anything.
    Otherwise use ``merge_queue_branch_expr``.
    """
    return f"{_source_pr_string(branch_column)} != ''"


def in_merge_queue_namespace_expr(branch_column: str) -> str:
    """HogQL predicate on the queue's branch namespace, for spend totals only.

    Wider than ``_SOURCE_PR_PATTERN``, so it also matches a gate branch that names no single PR.
    It does not check who pushed the branch. Otherwise use ``merge_queue_branch_expr``.
    """
    branch = f"ifNull({branch_column}, '')"
    return f"(startsWith({branch}, 'trunk-merge/') OR startsWith({branch}, 'gh-readonly-queue/'))"


def source_pr_string_expr(branch_column: str, *, queue_actor_column: str) -> str:
    """HogQL: the PR number a gate branch is landing, as a string, or '' when it is not a gate branch.

    ``queue_actor_column`` is the identity that pushed the branch: a run's ``actor``, a PR's ``user``
    or a span's ``ci.actor``. Any identity outside ``MERGE_QUEUE_BOT_HANDLES`` yields ''.
    """
    return f"if({_pushed_by_queue(queue_actor_column)}, {_source_pr_string(branch_column)}, '')"


def source_pr_number_expr(branch_column: str, *, queue_actor_column: str) -> str:
    """``source_pr_string_expr`` as an integer. 0 means not a gate branch, like the runs builder's
    ``pr_number`` for a run with no pull request."""
    string_expr = source_pr_string_expr(branch_column, queue_actor_column=queue_actor_column)
    return f"ifNull(accurateCastOrNull({string_expr}, 'Int64'), 0)"


def merge_queue_branch_expr(branch_column: str, *, queue_actor_column: str) -> str:
    """HogQL predicate: the branch is a gate branch that the queue pushed.

    True exactly when ``source_pr_number_expr`` resolves a PR. A prefix test would also match a branch
    with no resolvable PR, and its PR row would be dropped while its runs still point at it.
    """
    return f"{source_pr_number_expr(branch_column, queue_actor_column=queue_actor_column)} > 0"


def gate_attempt_expr(branch_column: str) -> str:
    """HogQL: the gate branch without Trunk's ``-bisection`` suffix, so a bisection probe groups with
    the attempt it investigates."""
    return f"replaceRegexpOne({branch_column}, '-bisection$', '')"


def gate_attempts_sql(
    *,
    runs_source: str,
    pull_requests_source: str,
    pull_request_filter: str,
    decisive_failure_conclusions_sql: str,
) -> str:
    """One row per merge-queue attempt. Runs that started after the merge are excluded before grouping.

    The query needs a ``gate_from`` placeholder.
    """
    return f"""
        SELECT
            r.pr_number AS pr_number,
            {gate_attempt_expr("r.head_branch")} AS attempt,
            min(r.run_started_at) AS started_at,
            max(r.updated_at) AS completed_at,
            countIf((r.status != 'completed' AND NOT r.stopped_reporting) OR r.updated_at IS NULL) AS unfinished,
            max(r.status = 'completed' AND r.conclusion IN ({decisive_failure_conclusions_sql})) AS failed,
            any(pr.merged_at) AS merged_at
        FROM {runs_source} AS r
        INNER JOIN {pull_requests_source} AS pr ON pr.number = r.pr_number
        WHERE r.is_merge_queue
            AND r.run_started_at >= {{gate_from}}
            AND (pr.merged_at IS NULL OR r.run_started_at <= pr.merged_at)
            AND ({pull_request_filter})
        GROUP BY r.pr_number, attempt
    """
