"""CI cost reads over the shared per-job cost source (``_curated.job_cost_source``).

Every read returns an empty result when the jobs source is not synced.
Each grouped query keeps an explicit ``LIMIT`` because HogQL otherwise caps a result at 100 rows.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from posthog.hogql import ast

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.facade.contracts import (
    CIEngine,
    CostPerMergeBucket,
    PRCostSummary,
    RunCost,
    WorkflowCost,
    WorkflowHealthRunScope,
    WorkflowRunnerCost,
)
from products.engineering_analytics.backend.logic.cost import (
    PRCostAggregate,
    render_is_billable_job,
    runner_tier_descriptor,
)
from products.engineering_analytics.backend.logic.merge_queue import in_merge_queue_namespace_expr
from products.engineering_analytics.backend.logic.queries._buckets import (
    Granularity,
    bucket_expr,
    normalize_bucket,
    window_buckets,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    UNPAGED_SCAN_LIMIT,
    branch_filter_clause,
    cost_run_scope_filter_clause,
    date_to_filter_clause,
    run_windowed_job_created_floor_constant,
    window_pair_predicates,
)

# A re-run copy sits on a billable tier but never executed, so this predicate puts it in excluded_jobs.
_BILLABLE_ROW = render_is_billable_job("c.provider", "c.os", "c.is_rerun_copy")


def _cost_aggregates(when: str = "1", suffix: str = "") -> str:
    """The five cost aggregate columns, in the order ``_aggregate`` takes them.

    ``when`` is a SQL predicate that gates every aggregate, and ``suffix`` is appended to each alias,
    so one scan can carry two windows. Every job is costed, unsettled or excluded.
    """
    return (
        f"sumIf(ifNull(c.billable_seconds, 0), {when}) AS billable_seconds{suffix}, "
        f"sumIf(c.estimated_cost_usd, c.estimated_cost_usd IS NOT NULL AND ({when})) AS cost_sum{suffix}, "
        f"countIf(c.estimated_cost_usd IS NOT NULL AND ({when})) AS costed_jobs{suffix}, "
        f"countIf({_BILLABLE_ROW} AND c.duration_seconds IS NULL AND ({when})) AS unsettled_jobs{suffix}, "
        f"countIf(NOT {_BILLABLE_ROW} AND ({when})) AS excluded_jobs{suffix}"
    )


def _aggregate(
    billable_seconds: float | None,
    cost_sum: float | None,
    costed: int | None,
    unsettled: int | None,
    excluded: int | None,
) -> PRCostAggregate:
    costed_jobs = int(costed or 0)
    return PRCostAggregate(
        billable_seconds=float(billable_seconds or 0.0),
        # A SQL sum over no rows is 0, so the costed count decides between $0.00 and no cost at all.
        estimated_cost_usd=float(cost_sum or 0.0) if costed_jobs else None,
        costed_jobs=costed_jobs,
        unsettled_jobs=int(unsettled or 0),
        excluded_jobs=int(excluded or 0),
    )


def _sum_aggregates(rows: Iterable[tuple]) -> PRCostAggregate:
    billable_seconds = cost_sum = 0.0
    costed = unsettled = excluded = 0
    for row_billable, row_cost, row_costed, row_unsettled, row_excluded in rows:
        billable_seconds += float(row_billable or 0.0)
        cost_sum += float(row_cost or 0.0)
        costed += int(row_costed or 0)
        unsettled += int(row_unsettled or 0)
        excluded += int(row_excluded or 0)
    return _aggregate(billable_seconds, cost_sum, costed, unsettled, excluded)


_EMPTY = PRCostSummary(
    jobs_available=False,
    billable_minutes=0.0,
    estimated_cost_usd=None,
    costed_jobs=0,
    unsettled_jobs=0,
    excluded_jobs=0,
    by_workflow=[],
    by_run=[],
)

# This query and _COSTS_BY_PR_SELECT without run_from have no scan floor, because they are keyed by
# PR number and CI associated with a PR can predate the PR's creation.
_PR_COST_SELECT = """
    SELECT
        c.workflow_name AS workflow_name,
        c.run_id AS run_id,
        c.run_attempt AS run_attempt,
        c.ci_engine AS ci_engine,
        __COST_AGGREGATES__
    FROM __COST_SOURCE__ AS c
    WHERE c.pr_number = {pr_number} AND c.repo_owner = {repo_owner} AND c.repo_name = {repo_name}
    GROUP BY c.workflow_name, c.run_id, c.run_attempt, c.ci_engine
    LIMIT 1000000
"""


def query_pr_cost(
    *,
    curated: CuratedGitHubSource,
    pr_number: int,
    repo_owner: str,
    repo_name: str,
) -> PRCostSummary:
    cost_source = curated.job_cost_source()
    if cost_source is None:
        return _EMPTY
    sql = _PR_COST_SELECT.replace("__COST_SOURCE__", cost_source).replace("__COST_AGGREGATES__", _cost_aggregates())
    response = curated.run(
        sql,
        query_type="engineering_analytics.pr_cost",
        placeholders={
            "pr_number": ast.Constant(value=pr_number),
            "repo_owner": ast.Constant(value=repo_owner),
            "repo_name": ast.Constant(value=repo_name),
        },
    )
    rows = response.results or []
    overall = _sum_aggregates(row[4:] for row in rows)
    by_workflow_rows: dict[str, list[tuple]] = defaultdict(list)
    by_run_rows: dict[tuple[CIEngine, int, int], list[tuple]] = defaultdict(list)
    for workflow, run_id, run_attempt, ci_engine, *agg in rows:
        by_workflow_rows[workflow or ""].append(tuple(agg))
        by_run_rows[(CIEngine(ci_engine), int(run_id), int(run_attempt))].append(tuple(agg))
    by_workflow = [
        _to_workflow_cost(workflow, _sum_aggregates(agg_rows))
        for workflow, agg_rows in sorted(by_workflow_rows.items())
    ]
    by_run = [
        _to_run_cost(run_id, run_attempt, _sum_aggregates(agg_rows), ci_engine=ci_engine)
        for (ci_engine, run_id, run_attempt), agg_rows in sorted(by_run_rows.items())
    ]

    return PRCostSummary(
        jobs_available=True,
        billable_minutes=overall.billable_seconds / 60,
        estimated_cost_usd=overall.estimated_cost_usd,
        costed_jobs=overall.costed_jobs,
        unsettled_jobs=overall.unsettled_jobs,
        excluded_jobs=overall.excluded_jobs,
        by_workflow=by_workflow,
        by_run=by_run,
    )


_COSTS_BY_PR_SELECT = f"""
    SELECT
        c.repo_owner AS repo_owner,
        c.repo_name AS repo_name,
        c.pr_number AS pr_number,
        __COST_AGGREGATES__
    FROM __COST_SOURCE__ AS c
    WHERE c.pr_number IN {{pr_numbers}} __RUN_FROM__
    GROUP BY c.repo_owner, c.repo_name, c.pr_number
    LIMIT {UNPAGED_SCAN_LIMIT}
"""


# The endpoint and MCP descriptions state that cost can lag new CI by this long.
_PR_COSTS_CACHE_SECONDS = 300
# The cache stores the SQL row, not a PRCostAggregate, because the cache key covers the SQL but not
# the Python classes that read the row.
_CostRow = tuple[str, str, float | None, float | None, int | None, int | None, int | None]
# (repo_owner, repo_name, pr_number). PR numbers restart per repository, so the number alone is not a key.
PullRequestKey = tuple[str, str, int]


def query_pr_costs(
    *, curated: CuratedGitHubSource, pr_numbers: list[int], run_from: datetime | None = None
) -> dict[PullRequestKey, PRCostAggregate]:
    """Cost per PR, keyed by (repo_owner, repo_name, pr_number). A PR with no jobs has no entry.

    With ``run_from``, runs started before it are left out and the result is not cached. Without it,
    the read covers each PR's whole CI history and is cached per PR.
    """
    scoped = run_from is None
    cost_source = curated.job_cost_source(created_floor=run_from is not None, since=run_from, scoped=scoped)
    if cost_source is None or not pr_numbers:
        return {}
    placeholders: dict[str, ast.Expr] = {"pr_numbers": ast.Constant(value=pr_numbers)}
    run_from_clause = ""
    if run_from is not None:
        placeholders["run_from"] = ast.Constant(value=run_from)
        placeholders["job_created_floor"] = run_windowed_job_created_floor_constant(run_from)
        run_from_clause = "AND c.run_started_at >= {run_from}"
    sql = (
        _COSTS_BY_PR_SELECT.replace("__COST_SOURCE__", cost_source)
        .replace("__COST_AGGREGATES__", _cost_aggregates())
        .replace("__RUN_FROM__", run_from_clause)
    )
    if scoped:
        sql = curated.scoped_to_pr_history(sql)

    def load(numbers: list[int]) -> dict[int, tuple[_CostRow, ...]]:
        response = curated.run(
            sql,
            query_type="engineering_analytics.pr_costs",
            placeholders={**placeholders, "pr_numbers": ast.Constant(value=numbers)},
        )
        by_number: dict[int, list[_CostRow]] = {number: [] for number in numbers}
        for repo_owner, repo_name, pr_number, *agg in response.results or []:
            by_number[int(pr_number)].append((repo_owner, repo_name, *agg))
        # A PR without costed jobs is stored too, so it does not bring the full jobs scan back on every view.
        return {number: tuple(costs) for number, costs in by_number.items()}

    if run_from is None:
        costs_by_number = curated.read_through(sql=sql, keys=pr_numbers, load=load, ttl_seconds=_PR_COSTS_CACHE_SECONDS)
    else:
        costs_by_number = load(pr_numbers)
    return {
        (repo_owner, repo_name, number): _aggregate(billable, cost, costed, unsettled, excluded)
        for number, costs in costs_by_number.items()
        for repo_owner, repo_name, billable, cost, costed, unsettled, excluded in costs
    }


_WINDOW_COST_SELECT = """
    SELECT c.workflow_name AS workflow_name, __COST_AGGREGATES__
    FROM __COST_SOURCE__ AS c
    WHERE c.run_started_at >= {date_from} __DATE_TO__ __BRANCH__ __RUN_SCOPE__
    GROUP BY c.workflow_name
    LIMIT 1000000
"""


def query_workflow_window_costs(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    branch: str | None,
    run_scope: WorkflowHealthRunScope,
    workload: Workload = Workload.DEFAULT,
) -> dict[str, PRCostAggregate]:
    """Cost per workflow over the window, keyed by workflow_name.

    The window, branch and run scope filter on the run's attributes, so a job whose run row is missing
    is left out and the population matches ``query_workflow_health``.
    """
    cost_source = curated.job_cost_source(created_floor=True, since=date_from)
    if cost_source is None:
        return {}
    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=date_from),
        "job_created_floor": run_windowed_job_created_floor_constant(date_from),
    }
    date_to_clause = date_to_filter_clause(date_to, placeholders, column="c.run_started_at")
    branch_clause = branch_filter_clause(branch, placeholders, column="c.run_head_branch")
    run_scope_clause = cost_run_scope_filter_clause(run_scope)
    sql = (
        _WINDOW_COST_SELECT.replace("__COST_SOURCE__", cost_source)
        .replace("__COST_AGGREGATES__", _cost_aggregates())
        .replace("__DATE_TO__", date_to_clause)
        .replace("__BRANCH__", branch_clause)
        .replace("__RUN_SCOPE__", run_scope_clause)
    )
    response = curated.run(
        sql, query_type="engineering_analytics.workflow_window_costs", placeholders=placeholders, workload=workload
    )
    return {(workflow or ""): _aggregate(*agg) for workflow, *agg in response.results or []}


# Runs join to the author's PRs on (repo_owner, repo_name, pr_number), because PR numbers restart per repo.
_AUTHOR_WORKFLOW_SELECT = """
    SELECT c.workflow_name AS workflow_name, __COST_AGGREGATES__
    FROM __COST_SOURCE__ AS c
    INNER JOIN (
            SELECT DISTINCT repo_owner, repo_name, number FROM __PR_SOURCE__ WHERE author_handle = {author}
        ) AS ap ON c.repo_owner = ap.repo_owner AND c.repo_name = ap.repo_name AND c.pr_number = ap.number
    WHERE c.run_started_at >= {date_from} __DATE_TO__
    GROUP BY c.workflow_name
    LIMIT 1000000
"""


def query_author_workflow_costs(
    *,
    curated: CuratedGitHubSource,
    author: str,
    date_from: datetime,
    date_to: datetime | None,
) -> list[WorkflowCost]:
    """Cost of the runs attributed to one author's PRs, split by workflow, highest spend first."""
    cost_source = curated.job_cost_source(created_floor=True, since=date_from)
    if cost_source is None:
        return []
    placeholders: dict[str, ast.Expr] = {
        "author": ast.Constant(value=author),
        "date_from": ast.Constant(value=date_from),
        "job_created_floor": run_windowed_job_created_floor_constant(date_from),
    }
    date_to_clause = ""
    if date_to is not None:
        date_to_clause = "AND c.run_started_at <= {date_to}"
        placeholders["date_to"] = ast.Constant(value=date_to)
    sql = (
        _AUTHOR_WORKFLOW_SELECT.replace("__COST_SOURCE__", cost_source)
        .replace("__COST_AGGREGATES__", _cost_aggregates())
        .replace("__PR_SOURCE__", curated.pr_source())
        .replace("__DATE_TO__", date_to_clause)
    )
    response = curated.run(sql, query_type="engineering_analytics.author_workflow_costs", placeholders=placeholders)
    costs = [_to_workflow_cost(workflow or "", _aggregate(*agg)) for workflow, *agg in response.results or []]
    return sorted(costs, key=lambda cost: (cost.estimated_cost_usd or 0.0, cost.billable_minutes), reverse=True)


_WINDOW_COST_WITH_PREV_SELECT = """
    SELECT c.workflow_name AS workflow_name, __CUR_AGG__, __PREV_AGG__, __QUEUE_AGG__, __DEPOT_CI_AGG__
    FROM __COST_SOURCE__ AS c
    WHERE c.run_started_at >= {prev_from} __DATE_TO__
    GROUP BY c.workflow_name
    LIMIT 1000000
"""


@dataclass(frozen=True, kw_only=True)
class WindowCostsWithPrev:
    by_workflow: dict[str, PRCostAggregate]
    by_workflow_prev: dict[str, PRCostAggregate]
    merge_queue_billable_seconds: float
    merge_queue_billable_seconds_prev: float
    depot_ci_billable_seconds: float
    depot_ci_billable_seconds_prev: float


_EMPTY_WINDOW_COSTS = WindowCostsWithPrev(
    by_workflow={},
    by_workflow_prev={},
    merge_queue_billable_seconds=0.0,
    merge_queue_billable_seconds_prev=0.0,
    depot_ci_billable_seconds=0.0,
    depot_ci_billable_seconds_prev=0.0,
)


def query_workflow_window_costs_with_prev(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    prev_from: datetime,
) -> WindowCostsWithPrev:
    """Cost per workflow for [date_from, date_to] and for [prev_from, date_from), from one scan.

    Both dicts are keyed by workflow_name. A workflow is in a window's dict only when it had a job in
    that window.
    """
    cost_source = curated.job_cost_source(created_floor=True, since=prev_from)
    if cost_source is None:
        return _EMPTY_WINDOW_COSTS
    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=date_from),
        "prev_from": ast.Constant(value=prev_from),
        "job_created_floor": run_windowed_job_created_floor_constant(prev_from),
        "depot_ci_engine": ast.Constant(value=CIEngine.DEPOT_CI.value),
    }
    windows = window_pair_predicates("c.run_started_at", date_to=date_to)
    date_to_clause = ""
    if date_to is not None:
        date_to_clause = "AND c.run_started_at <= {date_to}"
        placeholders["date_to"] = ast.Constant(value=date_to)
    # The namespace predicate counts all queue spend, including branch shapes that merge_queue.py
    # cannot resolve to a PR. merge_queue_overview.py reads a narrower population on purpose.
    queue = in_merge_queue_namespace_expr("c.head_branch")

    def slice_aggregates(predicate: str, alias: str) -> str:
        return (
            f"sumIf(ifNull(c.billable_seconds, 0), {predicate} AND {windows.current}) AS {alias}, "
            f"sumIf(ifNull(c.billable_seconds, 0), {predicate} AND {windows.previous}) AS {alias}_prev"
        )

    sql = (
        _WINDOW_COST_WITH_PREV_SELECT.replace("__COST_SOURCE__", cost_source)
        .replace("__CUR_AGG__", _cost_aggregates(when=windows.current))
        .replace("__PREV_AGG__", _cost_aggregates(when=windows.previous, suffix="_prev"))
        .replace("__QUEUE_AGG__", slice_aggregates(queue, "queue_billable_seconds"))
        .replace("__DEPOT_CI_AGG__", slice_aggregates("c.ci_engine = {depot_ci_engine}", "depot_ci_billable_seconds"))
        .replace("__DATE_TO__", date_to_clause)
    )
    response = curated.run(
        sql, query_type="engineering_analytics.workflow_window_costs_with_prev", placeholders=placeholders
    )
    by_workflow_cur: dict[str, PRCostAggregate] = {}
    by_workflow_prev: dict[str, PRCostAggregate] = {}
    slice_seconds = [0.0, 0.0, 0.0, 0.0]
    for workflow_name, *columns in response.results or []:
        workflow = workflow_name or ""
        cur_agg = _aggregate(*columns[0:5])
        prev_agg = _aggregate(*columns[5:10])
        if _has_jobs(cur_agg):
            by_workflow_cur[workflow] = cur_agg
        if _has_jobs(prev_agg):
            by_workflow_prev[workflow] = prev_agg
        slice_seconds = [total + float(value or 0.0) for total, value in zip(slice_seconds, columns[10:14])]
    queue_billable, queue_billable_prev, depot_ci_billable, depot_ci_billable_prev = slice_seconds
    return WindowCostsWithPrev(
        by_workflow=by_workflow_cur,
        by_workflow_prev=by_workflow_prev,
        merge_queue_billable_seconds=queue_billable,
        merge_queue_billable_seconds_prev=queue_billable_prev,
        depot_ci_billable_seconds=depot_ci_billable,
        depot_ci_billable_seconds_prev=depot_ci_billable_prev,
    )


_COST_SERIES_SELECT = """
    SELECT __BUCKET_FN__ AS bucket_start, __COST_AGGREGATES__
    FROM __COST_SOURCE__ AS c
    WHERE c.run_started_at >= {date_from} __DATE_TO__
    GROUP BY bucket_start
    LIMIT 1000000
"""

# Cost per merge divides over a trailing window of this many buckets. A per-bucket ratio has a hole
# in every bucket with no merge, and a PR's CI usually runs before the bucket it merges in.
# The first buckets of the series see a shorter window, because the scans start at date_from.
_ROLLING_BUCKETS: dict[Granularity, int] = {"hour": 24, "day": 7, "week": 4}

# Bots are counted, because the cost numerator counts every run whoever triggered it.
_MERGES_SERIES_SELECT = """
    SELECT __BUCKET_FN__ AS bucket_start, count() AS merges
    FROM __PR_SOURCE__ AS pr
    WHERE merged_at IS NOT NULL AND merged_at >= {date_from} __DATE_TO_MERGED__
    GROUP BY bucket_start
    LIMIT 40000
"""


def query_cost_per_merge_series(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    granularity: Granularity,
) -> list[CostPerMergeBucket]:
    """One bucket per ``granularity`` step across the window, oldest first, with no gaps.

    ``cost_per_merge_usd`` is the trailing-window ratio (see ``_ROLLING_BUCKETS``), while
    ``estimated_cost_usd`` and ``merges`` cover the bucket alone. Empty when the jobs source is not synced.
    """
    cost_source = curated.job_cost_source(created_floor=True, since=date_from)
    if cost_source is None:
        return []

    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=date_from),
        "job_created_floor": run_windowed_job_created_floor_constant(date_from),
    }
    date_to_runs = ""
    date_to_merged = ""
    if date_to is not None:
        date_to_runs = "AND c.run_started_at <= {date_to}"
        date_to_merged = "AND merged_at <= {date_to}"
        placeholders["date_to"] = ast.Constant(value=date_to)

    cost_sql = (
        _COST_SERIES_SELECT.replace("__COST_SOURCE__", cost_source)
        .replace("__COST_AGGREGATES__", _cost_aggregates())
        .replace("__BUCKET_FN__", bucket_expr(granularity, "c.run_started_at"))
        .replace("__DATE_TO__", date_to_runs)
    )
    cost_response = curated.run(
        cost_sql, query_type="engineering_analytics.cost_per_merge_cost", placeholders=placeholders
    )
    cost_by_bucket: dict[datetime, float | None] = {}
    for bucket_start, *agg in cost_response.results or []:
        cost_by_bucket[normalize_bucket(bucket_start, granularity)] = _aggregate(*agg).estimated_cost_usd

    merges_sql = (
        _MERGES_SERIES_SELECT.replace("__PR_SOURCE__", curated.pr_source())
        .replace("__BUCKET_FN__", bucket_expr(granularity, "merged_at"))
        .replace("__DATE_TO_MERGED__", date_to_merged)
    )
    merges_response = curated.run(
        merges_sql, query_type="engineering_analytics.cost_per_merge_merges", placeholders=placeholders
    )
    merges_by_bucket = {
        normalize_bucket(bucket_start, granularity): int(merges or 0)
        for bucket_start, merges in merges_response.results or []
    }

    spine = window_buckets(date_from, date_to, granularity)
    window = _ROLLING_BUCKETS[granularity]
    buckets: list[CostPerMergeBucket] = []
    for index, bucket in enumerate(spine):
        trailing = spine[max(0, index - window + 1) : index + 1]
        trailing_costs = [cost for b in trailing if (cost := cost_by_bucket.get(b)) is not None]
        trailing_cost = sum(trailing_costs) if trailing_costs else None
        trailing_merges = sum(merges_by_bucket.get(b, 0) for b in trailing)
        buckets.append(
            CostPerMergeBucket(
                bucket_start=bucket,
                estimated_cost_usd=cost_by_bucket.get(bucket),
                merges=merges_by_bucket.get(bucket, 0),
                cost_per_merge_usd=(trailing_cost / trailing_merges)
                if (trailing_cost is not None and trailing_merges)
                else None,
            )
        )
    return buckets


_RUNNER_COST_SELECT = """
    SELECT
        c.provider AS provider,
        c.os AS os,
        c.vcpu AS vcpu,
        count() AS job_count,
        __COST_AGGREGATES__
    FROM __COST_SOURCE__ AS c
    WHERE c.repo_owner = {repo_owner} AND c.repo_name = {repo_name} AND c.workflow_name = {workflow_name}
        AND c.run_started_at >= {date_from} __DATE_TO__ __BRANCH__ __RUN_SCOPE__
    GROUP BY c.provider, c.os, c.vcpu
    LIMIT 1000000
"""


def query_workflow_runner_costs(
    *,
    curated: CuratedGitHubSource,
    repo_owner: str,
    repo_name: str,
    workflow_name: str,
    date_from: datetime,
    date_to: datetime | None,
    branch: str | None = None,
    run_scope: WorkflowHealthRunScope = WorkflowHealthRunScope.ALL,
) -> list[WorkflowRunnerCost]:
    """One workflow's cost per (provider, os, vcpu) runner tier over the window, highest spend first."""
    cost_source = curated.job_cost_source(created_floor=True, since=date_from)
    if cost_source is None:
        return []
    placeholders: dict[str, ast.Expr] = {
        "repo_owner": ast.Constant(value=repo_owner),
        "repo_name": ast.Constant(value=repo_name),
        "workflow_name": ast.Constant(value=workflow_name),
        "date_from": ast.Constant(value=date_from),
        "job_created_floor": run_windowed_job_created_floor_constant(date_from),
    }
    date_to_clause = date_to_filter_clause(date_to, placeholders, column="c.run_started_at")
    branch_clause = branch_filter_clause(branch, placeholders, column="c.run_head_branch")
    run_scope_clause = cost_run_scope_filter_clause(run_scope)
    sql = (
        _RUNNER_COST_SELECT.replace("__COST_SOURCE__", cost_source)
        .replace("__COST_AGGREGATES__", _cost_aggregates())
        .replace("__DATE_TO__", date_to_clause)
        .replace("__BRANCH__", branch_clause)
        .replace("__RUN_SCOPE__", run_scope_clause)
    )
    response = curated.run(
        sql,
        query_type="engineering_analytics.workflow_runner_costs",
        placeholders=placeholders,
    )
    costs: list[WorkflowRunnerCost] = []
    for provider, os_, vcpu, job_count, *agg in response.results or []:
        aggregate = _aggregate(*agg)
        badge, label = runner_tier_descriptor(provider, os_, int(vcpu) if vcpu is not None else None)
        costs.append(
            WorkflowRunnerCost(
                provider=badge,
                runner_label=label,
                job_count=int(job_count),
                billable_minutes=aggregate.billable_seconds / 60,
                estimated_cost_usd=aggregate.estimated_cost_usd,
            )
        )
    return sorted(costs, key=lambda cost: (cost.estimated_cost_usd or 0.0, cost.billable_minutes), reverse=True)


def _has_jobs(aggregate: PRCostAggregate) -> bool:
    return bool(aggregate.costed_jobs + aggregate.unsettled_jobs + aggregate.excluded_jobs)


def _to_run_cost(run_id: int, run_attempt: int, aggregate: PRCostAggregate, *, ci_engine: CIEngine) -> RunCost:
    return RunCost(
        run_id=run_id,
        run_attempt=run_attempt,
        ci_engine=ci_engine,
        billable_minutes=aggregate.billable_seconds / 60,
        estimated_cost_usd=aggregate.estimated_cost_usd,
    )


def _to_workflow_cost(workflow_name: str, aggregate: PRCostAggregate) -> WorkflowCost:
    return WorkflowCost(
        workflow_name=workflow_name,
        billable_minutes=aggregate.billable_seconds / 60,
        estimated_cost_usd=aggregate.estimated_cost_usd,
        costed_jobs=aggregate.costed_jobs,
        unsettled_jobs=aggregate.unsettled_jobs,
        excluded_jobs=aggregate.excluded_jobs,
    )
