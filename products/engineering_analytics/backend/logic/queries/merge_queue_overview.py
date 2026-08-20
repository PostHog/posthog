"""Curated query: merge-queue landing stats for the repo hub landing page.

Gate-run attribution rides the runs builder's gate detection (SPEC §6, ``logic/merge_queue.py``):
``is_merge_queue`` marks actor-corroborated gate runs, ``pr_number`` is already re-keyed to the
source PR, and ``gate_attempt_expr`` names the attempt a run belongs to, so this module adds no
branch parsing of its own. The population is merged PRs with at
least one corroborated gate run: all authors, bots included, because these figures measure the
queue's mechanics, not author behavior (the locked bots/drafts recipe governs cycle-time medians,
a different question). ``had_failed_gate`` is a CI-outcome proxy for eviction: the queue's own
records are not in the GitHub source. Where a team syncs them (the opt-in Trunk merge-queue
table), ``query_merge_queue_trunk_outcomes`` reads the real verdicts instead.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from posthog.hogql import ast

from products.engineering_analytics.backend.logic.merge_queue import gate_attempt_expr
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource, opt_float
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    date_to_filter_clause,
    run_started_floor_constant,
    window_pair_predicates,
)

# Gate runs start minutes-to-hours before their merge; reach this far behind the previous window so
# a PR merged just inside it keeps its first attempt. Dwell beyond this truncates honestly: the
# first observed gate run anchors the measure.
_GATE_LOOKBACK = timedelta(days=7)

# Three layers so no SELECT reads an alias it defines: the inner select groups gate runs per source
# PR, the middle names the per-PR measure, the outer splits the current and previous windows on
# merge time. ``r.run_started_at <= merged_at`` keeps post-merge bisection runs out of both the
# first-gate anchor and the attempt count; a cancelled gate run counts as an attempt but not a
# failure (an attempt evicted by a neighbor's failure is not this PR's failure).
_MERGE_QUEUE_SELECT = """
    SELECT
        countIf(__CUR__) AS merged_cur,
        countIf(__PREV__) AS merged_prev,
        quantileIf(0.5)(gate_to_merge_seconds, __CUR__) AS median_cur,
        quantileIf(0.5)(gate_to_merge_seconds, __PREV__) AS median_prev,
        quantileIf(0.9)(gate_to_merge_seconds, __CUR__) AS p90_cur,
        quantileIf(0.9)(gate_to_merge_seconds, __PREV__) AS p90_prev,
        quantileIf(0.95)(gate_to_merge_seconds, __CUR__) AS p95_cur,
        quantileIf(0.95)(gate_to_merge_seconds, __PREV__) AS p95_prev,
        quantileIf(0.99)(gate_to_merge_seconds, __CUR__) AS p99_cur,
        quantileIf(0.99)(gate_to_merge_seconds, __PREV__) AS p99_prev,
        avgIf(attempts, __CUR__) AS avg_attempts_cur,
        avgIf(attempts, __PREV__) AS avg_attempts_prev,
        countIf(attempts > 1 AND __CUR__) / nullIf(countIf(__CUR__), 0) AS multi_attempt_share_cur,
        countIf(attempts > 1 AND __PREV__) / nullIf(countIf(__PREV__), 0) AS multi_attempt_share_prev,
        countIf(had_failed_gate AND __CUR__) / nullIf(countIf(__CUR__), 0) AS failed_gate_share_cur,
        countIf(had_failed_gate AND __PREV__) / nullIf(countIf(__PREV__), 0) AS failed_gate_share_prev
    FROM (
        SELECT
            pr_number,
            merged_at,
            dateDiff('second', first_gate_started_at, merged_at) AS gate_to_merge_seconds,
            attempts,
            had_failed_gate
        FROM (
            SELECT
                r.pr_number AS pr_number,
                any(pr.merged_at) AS merged_at,
                min(r.run_started_at) AS first_gate_started_at,
                count(DISTINCT __GATE_ATTEMPT__) AS attempts,
                max(r.status = 'completed' AND r.conclusion IN ('failure', 'timed_out')) AS had_failed_gate
            FROM __RUNS_SOURCE__ AS r
            INNER JOIN __PR_SOURCE__ AS pr ON pr.number = r.pr_number
            WHERE r.is_merge_queue
                AND r.run_started_at >= {gate_from}
                AND pr.merged_at IS NOT NULL
                AND r.run_started_at <= pr.merged_at
                AND pr.merged_at >= {prev_from} __DATE_TO_MERGED__
            GROUP BY r.pr_number
        )
    )
"""


@dataclass(frozen=True, kw_only=True)
class MergeQueueWindowStats:
    """Landing stats over merged PRs with at least one corroborated gate run, for a window and its
    previous twin. The percentiles measure first gate run start to merge, the observable anchor
    for enqueue-to-merge; pending time before gate testing starts is not visible in this data."""

    merged_pr_count: int
    merged_pr_count_prev: int
    median_first_gate_to_merge_seconds: float | None
    median_first_gate_to_merge_seconds_prev: float | None
    p90_first_gate_to_merge_seconds: float | None
    p90_first_gate_to_merge_seconds_prev: float | None
    p95_first_gate_to_merge_seconds: float | None
    p95_first_gate_to_merge_seconds_prev: float | None
    p99_first_gate_to_merge_seconds: float | None
    p99_first_gate_to_merge_seconds_prev: float | None
    avg_attempts_per_merge: float | None
    avg_attempts_per_merge_prev: float | None
    multi_attempt_merge_share: float | None
    multi_attempt_merge_share_prev: float | None
    failed_gate_merge_share: float | None
    failed_gate_merge_share_prev: float | None


_EMPTY_STATS = MergeQueueWindowStats(
    merged_pr_count=0,
    merged_pr_count_prev=0,
    median_first_gate_to_merge_seconds=None,
    median_first_gate_to_merge_seconds_prev=None,
    p90_first_gate_to_merge_seconds=None,
    p90_first_gate_to_merge_seconds_prev=None,
    p95_first_gate_to_merge_seconds=None,
    p95_first_gate_to_merge_seconds_prev=None,
    p99_first_gate_to_merge_seconds=None,
    p99_first_gate_to_merge_seconds_prev=None,
    avg_attempts_per_merge=None,
    avg_attempts_per_merge_prev=None,
    multi_attempt_merge_share=None,
    multi_attempt_merge_share_prev=None,
    failed_gate_merge_share=None,
    failed_gate_merge_share_prev=None,
)


# Trunk records each entry's terminal state directly, so eviction here is the queue's own verdict
# rather than the CI-outcome proxy above. Windowed on the entry's last state change because Trunk
# keeps no state history, so that approximates conclusion time.
_TRUNK_OUTCOMES_SELECT = """
    SELECT
        countIf(failed_or_cancelled AND __CUR__) / nullIf(countIf(concluded AND __CUR__), 0) AS failed_or_cancelled_share_cur,
        countIf(failed_or_cancelled AND __PREV__) / nullIf(countIf(concluded AND __PREV__), 0) AS failed_or_cancelled_share_prev,
        countIf(skip_the_line AND __CUR__) AS skip_the_line_cur,
        countIf(skip_the_line AND __PREV__) AS skip_the_line_prev
    FROM (
        SELECT
            state_changed_at,
            state IN ('merged', 'failed', 'cancelled') AS concluded,
            state IN ('failed', 'cancelled') AS failed_or_cancelled,
            skip_the_line
        FROM __TRUNK_SOURCE__
        WHERE state_changed_at >= {prev_from} __DATE_TO_CHANGED__
    )
"""


@dataclass(frozen=True, kw_only=True)
class TrunkQueueOutcomes:
    """Queue outcomes from Trunk's own records, for a window and its previous twin. Everything is
    None when no TrunkIo source has the merge-queue endpoint synced (``available``)."""

    available: bool
    failed_or_cancelled_share: float | None
    failed_or_cancelled_share_prev: float | None
    skip_the_line_count: int | None
    skip_the_line_count_prev: int | None


_TRUNK_UNAVAILABLE = TrunkQueueOutcomes(
    available=False,
    failed_or_cancelled_share=None,
    failed_or_cancelled_share_prev=None,
    skip_the_line_count=None,
    skip_the_line_count_prev=None,
)


def query_merge_queue_trunk_outcomes(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    prev_from: datetime,
) -> TrunkQueueOutcomes:
    """Trunk-recorded queue outcomes for [date_from, date_to] and [prev_from, date_from], one scan;
    the unavailable shape when the opt-in Trunk merge-queue table isn't synced."""
    source = curated.trunk_merge_queue_source()
    if source is None:
        return _TRUNK_UNAVAILABLE
    cur = "(state_changed_at >= {date_from}" + (" AND state_changed_at <= {date_to})" if date_to is not None else ")")
    prev = "(state_changed_at >= {prev_from} AND state_changed_at < {date_from})"
    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=date_from),
        "prev_from": ast.Constant(value=prev_from),
    }
    date_to_changed_clause = date_to_filter_clause(date_to, placeholders, column="state_changed_at")
    sql = (
        _TRUNK_OUTCOMES_SELECT.replace("__CUR__", cur)
        .replace("__PREV__", prev)
        .replace("__TRUNK_SOURCE__", source)
        .replace("__DATE_TO_CHANGED__", date_to_changed_clause)
    )
    response = curated.run(
        sql, query_type="engineering_analytics.merge_queue_trunk_outcomes", placeholders=placeholders
    )
    unmerged_cur, unmerged_prev, skip_cur, skip_prev = response.results[0] if response.results else (None, None, 0, 0)
    return TrunkQueueOutcomes(
        available=True,
        failed_or_cancelled_share=opt_float(unmerged_cur),
        failed_or_cancelled_share_prev=opt_float(unmerged_prev),
        skip_the_line_count=int(skip_cur or 0),
        skip_the_line_count_prev=int(skip_prev or 0),
    )


def query_merge_queue_overview(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    prev_from: datetime,
) -> MergeQueueWindowStats:
    """Merge-queue landing stats for [date_from, date_to] and [prev_from, date_from], one scan.

    The population keys on ``merged_at`` like every merge median; gate runs are scanned from
    ``prev_from - _GATE_LOOKBACK`` so a merge near the previous window's start keeps its early
    attempts.
    """
    gate_from = prev_from - _GATE_LOOKBACK
    windows = window_pair_predicates("merged_at", date_to=date_to)
    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=date_from),
        "prev_from": ast.Constant(value=prev_from),
        "gate_from": ast.Constant(value=gate_from),
        "run_started_floor": run_started_floor_constant(gate_from),
    }
    date_to_merged_clause = date_to_filter_clause(date_to, placeholders, column="pr.merged_at")
    sql = (
        _MERGE_QUEUE_SELECT.replace("__CUR__", windows.current)
        .replace("__PREV__", windows.previous)
        .replace("__RUNS_SOURCE__", curated.run_source(started_floor=True))
        .replace("__PR_SOURCE__", curated.pr_source())
        .replace("__GATE_ATTEMPT__", gate_attempt_expr("r.head_branch"))
        .replace("__DATE_TO_MERGED__", date_to_merged_clause)
    )
    response = curated.run(sql, query_type="engineering_analytics.merge_queue_overview", placeholders=placeholders)
    if not response.results:
        return _EMPTY_STATS
    (
        merged_cur,
        merged_prev,
        median_cur,
        median_prev,
        p90_cur,
        p90_prev,
        p95_cur,
        p95_prev,
        p99_cur,
        p99_prev,
        avg_attempts_cur,
        avg_attempts_prev,
        multi_share_cur,
        multi_share_prev,
        failed_share_cur,
        failed_share_prev,
    ) = response.results[0]
    return MergeQueueWindowStats(
        merged_pr_count=int(merged_cur or 0),
        merged_pr_count_prev=int(merged_prev or 0),
        median_first_gate_to_merge_seconds=opt_float(median_cur),
        median_first_gate_to_merge_seconds_prev=opt_float(median_prev),
        p90_first_gate_to_merge_seconds=opt_float(p90_cur),
        p90_first_gate_to_merge_seconds_prev=opt_float(p90_prev),
        p95_first_gate_to_merge_seconds=opt_float(p95_cur),
        p95_first_gate_to_merge_seconds_prev=opt_float(p95_prev),
        p99_first_gate_to_merge_seconds=opt_float(p99_cur),
        p99_first_gate_to_merge_seconds_prev=opt_float(p99_prev),
        avg_attempts_per_merge=opt_float(avg_attempts_cur),
        avg_attempts_per_merge_prev=opt_float(avg_attempts_prev),
        multi_attempt_merge_share=opt_float(multi_share_cur),
        multi_attempt_merge_share_prev=opt_float(multi_share_prev),
        failed_gate_merge_share=opt_float(failed_share_cur),
        failed_gate_merge_share_prev=opt_float(failed_share_prev),
    )
