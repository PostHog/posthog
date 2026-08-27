"""Curated query: repo-level headline aggregates for the repo hub landing page.

One runs scan covers the current window and the equal-length window before it, so
every headline number ships with its previous-window twin and the UI can render an
honest delta instead of a server-baked percentage. The PR medians (bots and drafts
excluded, per the locked cycle-time recipe) come from the PR snapshot the same way.

The chart series are a separate concern with a separate producer
(``query_repo_series``): every series query computes unconditionally (except the
ready-to-merge series, which is empty when that measure isn't observable), the
shared bucket granularity is decided exactly once, and a headline-only consumer
composes ``query_repo_overview`` with ``empty_repo_series`` instead of
flag-switching what the query layer computes.
"""

from dataclasses import dataclass
from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import (
    CostPerMergeBucket,
    OpenToMergeBucket,
    PassRateBucket,
    ReadyToMergeBucket,
    RepoOverview,
    TimeToGreenBucket,
)
from products.engineering_analytics.backend.logic.queries._buckets import (
    Granularity,
    bucket_expr,
    normalize_bucket,
    pick_granularity,
    window_buckets,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource, opt_float
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    run_started_floor_constant,
    window_pair_predicates,
)
from products.engineering_analytics.backend.logic.queries.merge_queue_overview import (
    query_merge_queue_overview,
    query_merge_queue_trunk_outcomes,
)
from products.engineering_analytics.backend.logic.queries.pr_cost import (
    query_cost_per_merge_series,
    query_workflow_window_costs_with_prev,
)
from products.engineering_analytics.backend.logic.queries.workflow_health import (
    query_time_to_green_series,
    query_time_to_green_window,
)

_RUNS_SELECT = """
    SELECT
        countIf(__CUR__) AS run_count,
        countIf(__PREV__) AS run_count_prev,
        countIf(status = 'completed' AND conclusion = 'success' AND __CUR__)
            / nullIf(countIf(status = 'completed' AND __CUR__), 0) AS success_rate,
        countIf(status = 'completed' AND conclusion = 'success' AND __PREV__)
            / nullIf(countIf(status = 'completed' AND __PREV__), 0) AS success_rate_prev,
        countIf(run_attempt > 1 AND __CUR__) AS rerun_cycles,
        countIf(run_attempt > 1 AND __PREV__) AS rerun_cycles_prev,
        countIf(head_branch = 'master' AND __CUR__) AS master_runs,
        countIf(head_branch = 'main' AND __CUR__) AS main_runs
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {prev_from} __DATE_TO__
"""

# The locked cycle-time recipe: a median over merges is a median over human, never-drafted PRs.
_HUMAN_MERGES = "NOT is_bot AND NOT is_draft"

# Medians follow the locked recipe; the merged counts deliberately don't — they are the merge
# population that triggered the CI spend, the same all-authors population the cost series' bucket-local
# merges count, so cost-per-merge ratios divide by a matching denominator.
_PR_SELECT = f"""
    SELECT
        quantileIf(0.5)(open_to_merge_seconds, __CUR_MERGED__ AND {_HUMAN_MERGES}) AS median_cur,
        quantileIf(0.5)(open_to_merge_seconds, __PREV_MERGED__ AND {_HUMAN_MERGES}) AS median_prev,
        __READY_MEDIAN_CUR__ AS ready_median_cur,
        __READY_MEDIAN_PREV__ AS ready_median_prev,
        countIf(__CUR_MERGED__) AS merged_cur,
        countIf(__PREV_MERGED__) AS merged_prev
    FROM __PR_SOURCE__ AS pr
    __READY_JOIN__
    WHERE merged_at IS NOT NULL AND merged_at >= {{prev_from}}
"""

_DEFAULT_BRANCH_SELECT = """
    SELECT countIf(head_branch = 'master') AS master_runs, countIf(head_branch = 'main') AS main_runs
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {date_from} __DATE_TO__
"""


def query_default_branch(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
) -> str:
    """'master' or 'main', by observed run volume in the window — the cheap standalone variant of the
    detection the overview aggregate gets for free."""
    date_to_clause = "AND run_started_at <= {date_to}" if date_to is not None else ""
    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=date_from),
        "run_started_floor": run_started_floor_constant(date_from),
    }
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)
    response = curated.run(
        _DEFAULT_BRANCH_SELECT.replace("__RUNS_SOURCE__", curated.run_source(started_floor=True)).replace(
            "__DATE_TO__", date_to_clause
        ),
        query_type="engineering_analytics.default_branch",
        placeholders=placeholders,
    )
    master_runs, main_runs = response.results[0] if response.results else (0, 0)
    return "main" if (main_runs or 0) > (master_runs or 0) else "master"


# Pass rate per bucket over completed runs, all branches — the population the headline pass rate uses.
# Division through nullIf yields NULL for a bucket with no completed run (a gap, not 0%).
_PASS_RATE_SERIES_SELECT = """
    SELECT
        __BUCKET_FN__ AS bucket_start,
        countIf(status = 'completed' AND conclusion = 'success') / nullIf(countIf(status = 'completed'), 0) AS success_rate
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {date_from} __DATE_TO__
    GROUP BY bucket_start
    LIMIT 40000
"""

# Median of a per-PR duration per bucket, over the PRs merged in it. The inner select applies the
# locked recipe once and names the measure, so a measure built from an expression (ready-to-merge)
# is written into the query exactly once. ``n`` guards the false zero: an aggregate over no sample
# returns 0, so a bucket whose only merges were bots, drafts, or PRs with no observed value would
# draw a false dip; report the gap (None) instead.
_MERGE_MEDIAN_SERIES_SELECT = f"""
    SELECT
        __BUCKET_FN__ AS bucket_start,
        quantile(0.5)(measure) AS p50,
        countIf(measure IS NOT NULL) AS n
    FROM (
        SELECT merged_at, __MEASURE__ AS measure
        FROM __PR_SOURCE__ AS pr
        __READY_JOIN__
        WHERE merged_at IS NOT NULL AND merged_at >= {{date_from}} __DATE_TO_MERGED__ AND {_HUMAN_MERGES}
    )
    GROUP BY bucket_start
    LIMIT 40000
"""


def _query_merge_median_series(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    granularity: Granularity,
    measure: str,
    join: str,
    with_clause: str,
    query_type: str,
) -> list[tuple[datetime, float | None]]:
    """``measure``'s median per bucket over the window's merges, oldest first and zero-filled: one
    ``(bucket_start, p50)`` pair per bucket, p50 None where the bucket had no sample."""
    placeholders: dict[str, ast.Expr] = {"date_from": ast.Constant(value=date_from)}
    date_to_clause = "AND merged_at <= {date_to}" if date_to is not None else ""
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)
    sql = with_clause + (
        _MERGE_MEDIAN_SERIES_SELECT.replace("__MEASURE__", measure)
        .replace("__READY_JOIN__", join)
        .replace("__PR_SOURCE__", curated.pr_source())
        .replace("__DATE_TO_MERGED__", date_to_clause)
        .replace("__BUCKET_FN__", bucket_expr(granularity, "merged_at"))
    )
    response = curated.run(sql, query_type=query_type, placeholders=placeholders)
    p50_by_bucket = {
        normalize_bucket(bucket_start, granularity): (opt_float(p50) if (n or 0) > 0 else None)
        for bucket_start, p50, n in response.results or []
    }
    return [(bucket, p50_by_bucket.get(bucket)) for bucket in window_buckets(date_from, date_to, granularity)]


def query_success_rate_series(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    granularity: Granularity,
) -> list[PassRateBucket]:
    """Pass rate per bucket across the window, oldest first: completed runs that succeeded, all branches —
    the same population as the headline pass rate. Empty buckets carry ``success_rate`` None (a gap)."""
    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=date_from),
        "run_started_floor": run_started_floor_constant(date_from),
    }
    date_to_clause = "AND run_started_at <= {date_to}" if date_to is not None else ""
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)
    sql = (
        _PASS_RATE_SERIES_SELECT.replace("__RUNS_SOURCE__", curated.run_source(started_floor=True))
        .replace("__DATE_TO__", date_to_clause)
        .replace("__BUCKET_FN__", bucket_expr(granularity, "run_started_at"))
    )
    response = curated.run(sql, query_type="engineering_analytics.success_rate_series", placeholders=placeholders)
    rate_by_bucket = {
        normalize_bucket(bucket_start, granularity): opt_float(success_rate)
        for bucket_start, success_rate in response.results or []
    }
    return [
        PassRateBucket(bucket_start=bucket, success_rate=rate_by_bucket.get(bucket))
        for bucket in window_buckets(date_from, date_to, granularity)
    ]


def query_ready_to_merge_series(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    granularity: Granularity,
) -> list[ReadyToMergeBucket]:
    """Median per-PR ready_to_merge_seconds (SPEC §6) per bucket, oldest first, bots and drafts
    excluded. Empty when the measure isn't observable, so a consumer falls back to the open-to-merge
    series rather than reading an all-gap line as "nothing merged"."""
    ready = curated.ready_to_merge_sql()
    if not ready.observable:
        return []
    return [
        ReadyToMergeBucket(bucket_start=bucket, p50_seconds=p50)
        for bucket, p50 in _query_merge_median_series(
            curated=curated,
            date_from=date_from,
            date_to=date_to,
            granularity=granularity,
            measure=ready.expr,
            join=ready.join,
            with_clause=ready.with_clause,
            query_type="engineering_analytics.ready_to_merge_series",
        )
    ]


def query_open_to_merge_series(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    granularity: Granularity,
) -> list[OpenToMergeBucket]:
    """Median time-to-merge per bucket across the window, oldest first: p50 merged_at - created_at over PRs
    merged in the bucket, bots and drafts excluded. Empty buckets carry ``p50_seconds`` None (a gap)."""
    return [
        OpenToMergeBucket(bucket_start=bucket, p50_seconds=p50)
        for bucket, p50 in _query_merge_median_series(
            curated=curated,
            date_from=date_from,
            date_to=date_to,
            granularity=granularity,
            measure="open_to_merge_seconds",
            join="",
            with_clause="",
            query_type="engineering_analytics.open_to_merge_series",
        )
    ]


@dataclass(frozen=True)
class RepoSeries:
    """The repo hub's chart series over one window, on one shared bucket granularity.

    Internal to the read layer: ``RepoOverview`` flattens it into the contract's per-series
    fields. Produced by ``query_repo_series`` (one bucketed scan per series) or ``empty_repo_series``
    (no scans — the headline-only shape), so callers compose which one they pay for instead
    of the query layer flag-switching what it computes.
    """

    granularity: Granularity
    cost: list[CostPerMergeBucket]
    time_to_green: list[TimeToGreenBucket]
    success_rate: list[PassRateBucket]
    open_to_merge: list[OpenToMergeBucket]
    ready_to_merge: list[ReadyToMergeBucket]


def query_repo_series(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
) -> RepoSeries:
    """All chart series across the window: the one place their shared granularity is decided."""
    granularity = pick_granularity(date_from, date_to)
    return RepoSeries(
        granularity=granularity,
        cost=query_cost_per_merge_series(
            curated=curated, date_from=date_from, date_to=date_to, granularity=granularity
        ),
        time_to_green=query_time_to_green_series(
            curated=curated, date_from=date_from, date_to=date_to, granularity=granularity
        ),
        success_rate=query_success_rate_series(
            curated=curated, date_from=date_from, date_to=date_to, granularity=granularity
        ),
        open_to_merge=query_open_to_merge_series(
            curated=curated, date_from=date_from, date_to=date_to, granularity=granularity
        ),
        ready_to_merge=query_ready_to_merge_series(
            curated=curated, date_from=date_from, date_to=date_to, granularity=granularity
        ),
    )


def empty_repo_series(*, date_from: datetime, date_to: datetime | None) -> RepoSeries:
    """The series a headline-only read carries: no buckets, no scans, but the same granularity a
    full read would use, so the contract's non-null granularity fields stay meaningful."""
    return RepoSeries(
        granularity=pick_granularity(date_from, date_to),
        cost=[],
        time_to_green=[],
        success_rate=[],
        open_to_merge=[],
        ready_to_merge=[],
    )


def query_repo_overview(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    series: RepoSeries,
) -> RepoOverview:
    end = date_to or datetime.now(tz=date_from.tzinfo)
    prev_from = date_from - (end - date_from)
    date_to_clause = "AND run_started_at <= {date_to}" if date_to is not None else ""
    run_windows = window_pair_predicates("run_started_at", date_to=date_to)

    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=date_from),
        "prev_from": ast.Constant(value=prev_from),
        # The scan reaches back to prev_from (the previous comparison window), so the raw floor
        # comes from prev_from, not date_from — a date_from floor would cut the prev-window rows.
        "run_started_floor": run_started_floor_constant(prev_from),
    }
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)

    runs_sql = (
        _RUNS_SELECT.replace("__CUR__", run_windows.current)
        .replace("__PREV__", run_windows.previous)
        .replace("__RUNS_SOURCE__", curated.run_source(started_floor=True))
        .replace("__DATE_TO__", date_to_clause)
    )
    runs_response = curated.run(
        runs_sql, query_type="engineering_analytics.repo_overview_runs", placeholders=placeholders
    )
    row = runs_response.results[0] if runs_response.results else (0, 0, None, None, 0, 0, 0, 0)
    run_count, run_count_prev, success_rate, success_rate_prev, reruns, reruns_prev, master_runs, main_runs = row
    default_branch = "main" if (main_runs or 0) > (master_runs or 0) else "master"

    merge_windows = window_pair_predicates("merged_at", date_to=date_to)
    ready = curated.ready_to_merge_sql()
    pr_sql = ready.with_clause + (
        _PR_SELECT.replace("__READY_MEDIAN_CUR__", ready.median(scope=f"{merge_windows.current} AND {_HUMAN_MERGES}"))
        .replace("__READY_MEDIAN_PREV__", ready.median(scope=f"{merge_windows.previous} AND {_HUMAN_MERGES}"))
        .replace("__READY_JOIN__", ready.join)
        .replace("__CUR_MERGED__", merge_windows.current)
        .replace("__PREV_MERGED__", merge_windows.previous)
        .replace("__PR_SOURCE__", curated.pr_source())
    )
    pr_response = curated.run(pr_sql, query_type="engineering_analytics.repo_overview_prs", placeholders=placeholders)
    median_cur, median_prev, ready_median_cur, ready_median_prev, merged_cur, merged_prev = (
        pr_response.results[0] if pr_response.results else (None, None, None, None, 0, 0)
    )

    jobs_available = curated.jobs_source() is not None
    queue = query_merge_queue_overview(curated=curated, date_from=date_from, date_to=date_to, prev_from=prev_from)
    trunk = query_merge_queue_trunk_outcomes(curated=curated, date_from=date_from, date_to=date_to, prev_from=prev_from)
    time_to_green = query_time_to_green_window(
        curated=curated, date_from=date_from, date_to=date_to, prev_from=prev_from
    )
    costs = query_workflow_window_costs_with_prev(
        curated=curated, date_from=date_from, date_to=date_to, prev_from=prev_from
    )
    cost_cur, cost_prev = costs.by_workflow, costs.by_workflow_prev
    # Per-workflow figures can be None (billable time on an unknown tier) — sum what's known.
    billable_seconds = sum(c.billable_seconds or 0.0 for c in cost_cur.values()) if cost_cur else None
    billable_seconds_prev = sum(c.billable_seconds or 0.0 for c in cost_prev.values()) if cost_prev else None
    cost_usd = sum(c.estimated_cost_usd or 0.0 for c in cost_cur.values()) if cost_cur else None
    cost_usd_prev = sum(c.estimated_cost_usd or 0.0 for c in cost_prev.values()) if cost_prev else None
    # The queue slice mirrors billable_minutes' null gating so both go null together.
    queue_minutes = costs.merge_queue_billable_seconds / 60 if cost_cur else None
    queue_minutes_prev = costs.merge_queue_billable_seconds_prev / 60 if cost_prev else None
    cost_per_merge = cost_usd / int(merged_cur) if cost_usd is not None and merged_cur else None
    cost_per_merge_prev = cost_usd_prev / int(merged_prev) if cost_usd_prev is not None and merged_prev else None

    return RepoOverview(
        run_count=run_count,
        run_count_prev=run_count_prev,
        success_rate=opt_float(success_rate),
        success_rate_prev=opt_float(success_rate_prev),
        rerun_cycles=reruns,
        rerun_cycles_prev=reruns_prev,
        merged_pr_count=int(merged_cur or 0),
        merged_pr_count_prev=int(merged_prev or 0),
        median_open_to_merge_seconds=opt_float(median_cur),
        median_open_to_merge_seconds_prev=opt_float(median_prev),
        median_ready_to_merge_seconds=opt_float(ready_median_cur),
        median_ready_to_merge_seconds_prev=opt_float(ready_median_prev),
        billable_minutes=billable_seconds / 60 if billable_seconds is not None else None,
        billable_minutes_prev=billable_seconds_prev / 60 if billable_seconds_prev is not None else None,
        estimated_cost_usd=opt_float(cost_usd),
        estimated_cost_usd_prev=opt_float(cost_usd_prev),
        cost_per_merge_usd=opt_float(cost_per_merge),
        cost_per_merge_usd_prev=opt_float(cost_per_merge_prev),
        merge_queue_billable_minutes=queue_minutes,
        merge_queue_billable_minutes_prev=queue_minutes_prev,
        merge_queue_merged_pr_count=queue.merged_pr_count,
        merge_queue_merged_pr_count_prev=queue.merged_pr_count_prev,
        merge_queue_median_first_gate_to_merge_seconds=queue.median_first_gate_to_merge_seconds,
        merge_queue_median_first_gate_to_merge_seconds_prev=queue.median_first_gate_to_merge_seconds_prev,
        merge_queue_p90_first_gate_to_merge_seconds=queue.p90_first_gate_to_merge_seconds,
        merge_queue_p90_first_gate_to_merge_seconds_prev=queue.p90_first_gate_to_merge_seconds_prev,
        merge_queue_p95_first_gate_to_merge_seconds=queue.p95_first_gate_to_merge_seconds,
        merge_queue_p95_first_gate_to_merge_seconds_prev=queue.p95_first_gate_to_merge_seconds_prev,
        merge_queue_p99_first_gate_to_merge_seconds=queue.p99_first_gate_to_merge_seconds,
        merge_queue_p99_first_gate_to_merge_seconds_prev=queue.p99_first_gate_to_merge_seconds_prev,
        merge_queue_avg_attempts_per_merge=queue.avg_attempts_per_merge,
        merge_queue_avg_attempts_per_merge_prev=queue.avg_attempts_per_merge_prev,
        merge_queue_multi_attempt_merge_share=queue.multi_attempt_merge_share,
        merge_queue_multi_attempt_merge_share_prev=queue.multi_attempt_merge_share_prev,
        merge_queue_failed_gate_merge_share=queue.failed_gate_merge_share,
        merge_queue_failed_gate_merge_share_prev=queue.failed_gate_merge_share_prev,
        merge_queue_trunk_available=trunk.available,
        merge_queue_failed_or_cancelled_share=trunk.failed_or_cancelled_share,
        merge_queue_failed_or_cancelled_share_prev=trunk.failed_or_cancelled_share_prev,
        merge_queue_skip_the_line_count=trunk.skip_the_line_count,
        merge_queue_skip_the_line_count_prev=trunk.skip_the_line_count_prev,
        median_time_to_green_seconds=time_to_green.median_seconds,
        median_time_to_green_seconds_prev=time_to_green.median_seconds_prev,
        jobs_available=jobs_available,
        default_branch=default_branch,
        cost_series=series.cost,
        cost_series_granularity=series.granularity,
        time_to_green_series=series.time_to_green,
        time_to_green_series_granularity=series.granularity,
        success_rate_series=series.success_rate,
        success_rate_series_granularity=series.granularity,
        open_to_merge_series=series.open_to_merge,
        open_to_merge_series_granularity=series.granularity,
        ready_to_merge_series=series.ready_to_merge,
        ready_to_merge_series_granularity=series.granularity,
    )
