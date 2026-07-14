"""HogQL assembly of a PR's estimated CI cost, summed over the jobs of all its runs.

Cost is job-level: a run fans into parallel jobs on different runner tiers, so per-PR cost is a sum
over jobs (see ``logic.cost``). Every query here reads the shared per-job cost source
(``_curated.job_cost_source`` — the same rendered model the exposed ``engineering_analytics_job_costs``
view computes) and aggregates the per-job ``billable_seconds`` / ``estimated_cost_usd`` in SQL, so
cost is computed exactly once, in ClickHouse, from the ``logic.cost`` constants. When the jobs source
isn't synced, ``job_cost_source()`` is None and these return empty results (``jobs_available=False``)
so the UI hides the cost cards instead of erroring.

The three-bucket partition (costed / unsettled / excluded) is the SQL twin of the old Python rollup:
a job is costed when its rendered ``estimated_cost_usd`` is non-NULL (billable self-hosted Linux with
a known elapsed — including a real 0.0 for a non-positive elapsed), unsettled when it is a billable
tier with no elapsed yet, and excluded otherwise. ``estimated_cost_usd`` is reconstructed as None when
nothing was costable (a SQL sum over an empty set is 0, which must read as "nothing to cost", never a
real $0.00). Grouped results are small, but each query keeps an explicit ``LIMIT`` so a wide scope
(the PR list scans up to a thousand PRs) can't hit HogQL's default 100-row cap.
"""

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import (
    CostPerMergeBucket,
    PRCostSummary,
    RunCost,
    WorkflowCost,
    WorkflowHealthRunScope,
    WorkflowRunnerCost,
)
from products.engineering_analytics.backend.logic.cost import (
    PRCostAggregate,
    render_is_billable_tier,
    runner_tier_descriptor,
)
from products.engineering_analytics.backend.logic.queries._buckets import (
    Granularity,
    bucket_expr,
    normalize_bucket,
    window_buckets,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    branch_filter_clause,
    date_to_filter_clause,
    run_scope_filter_clause,
)

# The billable-tier predicate over the cost source's classified columns — defined once in logic.cost
# so 'depot'/'linux' never appear as literals here.
_BILLABLE_TIER = render_is_billable_tier("c.provider", "c.os")


def _cost_aggregates(when: str = "1", suffix: str = "") -> str:
    """The five per-scope cost aggregates over the cost source, optionally gated by ``when`` (a SQL
    predicate, e.g. a window) and suffixed so a single scan can carry two windows side by side.

    ``billable_seconds`` sums ``greatest(elapsed, 0)`` over costed rows; ``cost_sum`` sums the rendered
    per-job dollar cost; ``costed_jobs`` counts rows with a non-NULL cost; ``unsettled_jobs`` and
    ``excluded_jobs`` complete the three-bucket partition. ``costed_jobs`` is what tells "$0.00" apart
    from "nothing to cost" downstream — a SQL sum can't.
    """
    return (
        f"sumIf(ifNull(c.billable_seconds, 0), {when}) AS billable_seconds{suffix}, "
        f"sumIf(c.estimated_cost_usd, c.estimated_cost_usd IS NOT NULL AND ({when})) AS cost_sum{suffix}, "
        f"countIf(c.estimated_cost_usd IS NOT NULL AND ({when})) AS costed_jobs{suffix}, "
        f"countIf({_BILLABLE_TIER} AND c.duration_seconds IS NULL AND ({when})) AS unsettled_jobs{suffix}, "
        f"countIf(NOT {_BILLABLE_TIER} AND ({when})) AS excluded_jobs{suffix}"
    )


def _aggregate(
    billable_seconds: float | None,
    cost_sum: float | None,
    costed: int | None,
    unsettled: int | None,
    excluded: int | None,
) -> PRCostAggregate:
    """Build a ``PRCostAggregate`` from one grouped SQL row's five cost columns."""
    costed_jobs = int(costed or 0)
    return PRCostAggregate(
        billable_seconds=float(billable_seconds or 0.0),
        # None (not 0.0) when nothing was costable, so an all-unsettled/excluded scope reads honestly.
        estimated_cost_usd=float(cost_sum or 0.0) if costed_jobs else None,
        costed_jobs=costed_jobs,
        unsettled_jobs=int(unsettled or 0),
        excluded_jobs=int(excluded or 0),
    )


def _sum_aggregates(rows: Iterable[tuple]) -> PRCostAggregate:
    """Fold several grouped cost rows (five columns each) into one aggregate — cost is linear, so
    summing finer-grained groups is exact. Used to roll the per-(workflow, run) rows of a PR up to
    per-workflow and whole-PR totals from a single query."""
    billable_seconds = cost_sum = 0.0
    costed = unsettled = excluded = 0
    for row_billable, row_cost, row_costed, row_unsettled, row_excluded in rows:
        billable_seconds += float(row_billable or 0.0)
        cost_sum += float(row_cost or 0.0)
        costed += int(row_costed or 0)
        unsettled += int(row_unsettled or 0)
        excluded += int(row_excluded or 0)
    # Delegate the PRCostAggregate construction (incl. the None-vs-$0.00 rule) to _aggregate, so that
    # rule lives in exactly one place — the folded columns are just its five inputs.
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

# One grouped scan of the PR's jobs at the finest grain (workflow × run attempt); the whole-PR,
# per-workflow, and per-run rollups all fold from these rows in Python (cost is linear). Filtering on
# the cost source's run-attribution columns (pr_number is 0→NULL normalized) drops jobs whose run row
# is missing, matching the legacy INNER JOIN population.
_PR_COST_SELECT = """
    SELECT
        c.workflow_name AS workflow_name,
        c.run_id AS run_id,
        c.run_attempt AS run_attempt,
        __COST_AGGREGATES__
    FROM __COST_SOURCE__ AS c
    WHERE c.pr_number = {pr_number} AND c.repo_owner = {repo_owner} AND c.repo_name = {repo_name}
    GROUP BY c.workflow_name, c.run_id, c.run_attempt
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
        # The optional job-level source isn't synced for this team yet — no honest cost to report.
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
    overall = _sum_aggregates(row[3:] for row in rows)
    by_workflow_rows: dict[str, list[tuple]] = defaultdict(list)
    by_run_rows: dict[tuple[int, int], list[tuple]] = defaultdict(list)
    for workflow, run_id, run_attempt, *agg in rows:
        by_workflow_rows[workflow or ""].append(tuple(agg))
        by_run_rows[(int(run_id), int(run_attempt))].append(tuple(agg))
    by_workflow = [
        _to_workflow_cost(workflow, _sum_aggregates(agg_rows))
        for workflow, agg_rows in sorted(by_workflow_rows.items())
    ]
    by_run = [
        _to_run_cost(run_id, run_attempt, _sum_aggregates(agg_rows))
        for (run_id, run_attempt), agg_rows in sorted(by_run_rows.items())
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


# Per-PR billable cost across the given PR numbers, aggregated in SQL and scoped to the visible PR
# numbers so a team with deep CI history doesn't pay an all-time scan per page.
_LIST_COST_SELECT = """
    SELECT
        c.repo_owner AS repo_owner,
        c.repo_name AS repo_name,
        c.pr_number AS pr_number,
        __COST_AGGREGATES__
    FROM __COST_SOURCE__ AS c
    WHERE c.pr_number IN {pr_numbers}
    GROUP BY c.repo_owner, c.repo_name, c.pr_number
    LIMIT 1000000
"""


def query_pr_list_costs(
    *, curated: CuratedGitHubSource, pr_numbers: list[int]
) -> dict[tuple[str, str, int], PRCostAggregate]:
    """Per-PR billable cost across the given PR numbers' runs, keyed by (repo_owner, repo_name, pr_number).

    Empty when the jobs source isn't synced or no PR numbers are given. One grouped pass over the cost
    source so the PR list can show a cost/minutes column per row without a query per PR; scoped to the
    visible PR numbers so the scan tracks the page, not the team's whole CI history.
    """
    cost_source = curated.job_cost_source()
    if cost_source is None or not pr_numbers:
        return {}
    sql = _LIST_COST_SELECT.replace("__COST_SOURCE__", cost_source).replace("__COST_AGGREGATES__", _cost_aggregates())
    response = curated.run(
        sql,
        query_type="engineering_analytics.pr_list_costs",
        placeholders={"pr_numbers": ast.Constant(value=pr_numbers)},
    )
    return {
        (repo_owner, repo_name, int(pr_number)): _aggregate(*agg)
        for repo_owner, repo_name, pr_number, *agg in response.results or []
    }


# Per-workflow billable cost over a window (Workflows tab), grouped and costed in SQL and keyed by
# workflow_name. Windowed and optionally branch/run-scope filtered on the run's attributes (the cost
# source carries run_started_at and run_head_branch alongside the per-job cost columns).
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
) -> dict[str, PRCostAggregate]:
    """Per-workflow billable cost over [date_from, date_to] (optional branch/run_scope), keyed by workflow_name.

    Empty when the jobs source isn't synced. Grouped per workflow in SQL over the shared cost source;
    the window/branch/run_scope predicates read the run's attributes, so the population matches the
    run-level ``query_workflow_health`` (a job whose run is missing has a NULL run_started_at and is
    excluded by the window filter, matching the legacy INNER JOIN).
    """
    cost_source = curated.job_cost_source()
    if cost_source is None:
        return {}
    placeholders: dict[str, ast.Expr] = {"date_from": ast.Constant(value=date_from)}
    date_to_clause = date_to_filter_clause(date_to, placeholders, column="c.run_started_at")
    branch_clause = branch_filter_clause(branch, placeholders, column="c.run_head_branch")
    run_scope_clause = run_scope_filter_clause(
        run_scope, branch_column="c.run_head_branch", attributed_predicate="c.pr_number IS NOT NULL"
    )
    sql = (
        _WINDOW_COST_SELECT.replace("__COST_SOURCE__", cost_source)
        .replace("__COST_AGGREGATES__", _cost_aggregates())
        .replace("__DATE_TO__", date_to_clause)
        .replace("__BRANCH__", branch_clause)
        .replace("__RUN_SCOPE__", run_scope_clause)
    )
    response = curated.run(sql, query_type="engineering_analytics.workflow_window_costs", placeholders=placeholders)
    return {(workflow or ""): _aggregate(*agg) for workflow, *agg in response.results or []}


# One author's CI spend split by workflow (the author page's "where their CI minutes go"). Runs are
# attributed to the author through their PRs, keyed on (repo_owner, repo_name, pr_number) — never
# pr_number alone, since PR numbers restart per repo (SPEC §7). Windowed on the run start so the figure
# answers "spend over [window]", never an unbounded all-time.
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
    """One author's billable CI cost split by workflow over [date_from, date_to], highest spend first.

    Empty when the jobs source isn't synced. Grouped and costed in SQL over the shared cost source; the
    author→runs link goes through their PR numbers (the one attribution rule, SPEC §7) — the cost
    source's normalized pr_number never matches on an unattributed (NULL) run.
    """
    cost_source = curated.job_cost_source()
    if cost_source is None:
        return []
    placeholders: dict[str, ast.Expr] = {
        "author": ast.Constant(value=author),
        "date_from": ast.Constant(value=date_from),
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


# The window-cost shape twice over — the current window and the equal-length one before it — as
# per-window conditional aggregates on one cost-source scan, so the repo hub's delta doesn't pay the
# scan twice. The previous window is half-open ([prev_from, date_from)) so no run lands in both.
_WINDOW_COST_WITH_PREV_SELECT = """
    SELECT c.workflow_name AS workflow_name, __CUR_AGG__, __PREV_AGG__
    FROM __COST_SOURCE__ AS c
    WHERE c.run_started_at >= {prev_from} __DATE_TO__
    GROUP BY c.workflow_name
    LIMIT 1000000
"""


def query_workflow_window_costs_with_prev(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    prev_from: datetime,
) -> tuple[dict[str, PRCostAggregate], dict[str, PRCostAggregate]]:
    """``query_workflow_window_costs`` for [date_from, date_to] and [prev_from, date_from] in one scan.

    Returns ``(current, previous)``, both keyed by workflow_name; empty when the jobs source isn't synced.
    A workflow lands in a window's dict only when it had at least one job in that window (same as the
    prior implementation), so a workflow present only in the other window doesn't create a phantom
    zero-cost entry.
    """
    cost_source = curated.job_cost_source()
    if cost_source is None:
        return {}, {}
    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=date_from),
        "prev_from": ast.Constant(value=prev_from),
    }
    cur = "(c.run_started_at >= {date_from}" + (" AND c.run_started_at <= {date_to})" if date_to else ")")
    # Half-open: a run starting exactly at date_from is current, not both windows.
    prev = "(c.run_started_at >= {prev_from} AND c.run_started_at < {date_from})"
    date_to_clause = ""
    if date_to is not None:
        date_to_clause = "AND c.run_started_at <= {date_to}"
        placeholders["date_to"] = ast.Constant(value=date_to)
    sql = (
        _WINDOW_COST_WITH_PREV_SELECT.replace("__COST_SOURCE__", cost_source)
        .replace("__CUR_AGG__", _cost_aggregates(when=cur))
        .replace("__PREV_AGG__", _cost_aggregates(when=prev, suffix="_prev"))
        .replace("__DATE_TO__", date_to_clause)
    )
    response = curated.run(
        sql, query_type="engineering_analytics.workflow_window_costs_with_prev", placeholders=placeholders
    )
    by_workflow_cur: dict[str, PRCostAggregate] = {}
    by_workflow_prev: dict[str, PRCostAggregate] = {}
    for workflow_name, *columns in response.results or []:
        workflow = workflow_name or ""
        cur_agg = _aggregate(*columns[0:5])
        prev_agg = _aggregate(*columns[5:10])
        if _has_jobs(cur_agg):
            by_workflow_cur[workflow] = cur_agg
        if _has_jobs(prev_agg):
            by_workflow_prev[workflow] = prev_agg
    return by_workflow_cur, by_workflow_prev


# CI cost per merged PR over time (repo hub's Cost section trend). Two bucketed scans — cost by run
# start, merges by merge time — folded together per bucket. Cost is aggregated in SQL over the shared
# cost source (same rendered model as every other cost surface); only the per-bucket dollar figure
# crosses back to Python.
_COST_SERIES_SELECT = """
    SELECT __BUCKET_FN__ AS bucket_start, __COST_AGGREGATES__
    FROM __COST_SOURCE__ AS c
    WHERE c.run_started_at >= {date_from} __DATE_TO__
    GROUP BY bucket_start
    LIMIT 1000000
"""

# The headline ratio is a trailing rolling window, not a per-bucket division: a strict per-bucket
# cost/merges has a hole in every bucket that shipped nothing (most hours, quiet weekends), and it
# pairs a bucket's spend with that same bucket's merges even though a PR's CI usually ran before its
# merge bucket. Summing cost and merges over a trailing window sized to the grain smooths both out
# while keeping the whole-bill economics (master/scheduled spend included). Buckets near date_from
# see a partial window — the scans are window-bounded, so there's no pre-window data to reach back to.
_ROLLING_BUCKETS: dict[Granularity, int] = {"hour": 24, "day": 7, "week": 4}

# Merged PRs per bucket — the divisor. All authors and bots, no draft/bot filter, so the population
# matches the cost numerator (every run counted, whoever triggered it); a merged PR is never a draft.
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
    """CI cost per merged PR across [date_from, date_to] at ``granularity``, oldest first.

    Buckets are zero-filled across the whole window so the trend has no gaps; each bucket's
    ``cost_per_merge_usd`` is the trailing-window ratio (see ``_ROLLING_BUCKETS``) while
    ``estimated_cost_usd``/``merges`` stay bucket-local. When the job-level source isn't synced
    there's no cost to divide, so the series is empty (the UI shows the same "sync jobs" state as
    the other cost surfaces).
    """
    cost_source = curated.job_cost_source()
    if cost_source is None:
        return []

    placeholders: dict[str, ast.Expr] = {"date_from": ast.Constant(value=date_from)}
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


# Per-runner-tier cost for one workflow (single-workflow page "where the spend goes" breakdown), scoped
# to the page's run window (and optional branch) so the figure always answers "spend over [window]",
# never an unbounded all-time. Grouped by the rendered (provider, os, vcpu) tier in SQL — the cost
# source already classifies each job — and mapped to a display badge/label in Python.
_RUNNER_COST_SELECT = """
    SELECT
        c.provider AS provider,
        c.os AS os,
        c.vcpu AS vcpu,
        count() AS job_count,
        __COST_AGGREGATES__
    FROM __COST_SOURCE__ AS c
    WHERE c.repo_owner = {repo_owner} AND c.repo_name = {repo_name} AND c.workflow_name = {workflow_name}
        AND c.run_started_at >= {date_from} __DATE_TO__ __BRANCH__
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
) -> list[WorkflowRunnerCost]:
    """A workflow's CI cost broken down by runner tier over [date_from, date_to] (optional branch),
    highest spend first. Empty when the jobs source isn't synced. Grouped by the rendered
    (provider, os, vcpu) tier and mapped to its display badge/label via ``runner_tier_descriptor``."""
    cost_source = curated.job_cost_source()
    if cost_source is None:
        return []
    placeholders: dict[str, ast.Expr] = {
        "repo_owner": ast.Constant(value=repo_owner),
        "repo_name": ast.Constant(value=repo_name),
        "workflow_name": ast.Constant(value=workflow_name),
        "date_from": ast.Constant(value=date_from),
    }
    date_to_clause = date_to_filter_clause(date_to, placeholders, column="c.run_started_at")
    branch_clause = branch_filter_clause(branch, placeholders, column="c.run_head_branch")
    sql = (
        _RUNNER_COST_SELECT.replace("__COST_SOURCE__", cost_source)
        .replace("__COST_AGGREGATES__", _cost_aggregates())
        .replace("__DATE_TO__", date_to_clause)
        .replace("__BRANCH__", branch_clause)
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
    """True when the aggregate covers at least one job (any bucket) — the "this window had runs" test."""
    return bool(aggregate.costed_jobs + aggregate.unsettled_jobs + aggregate.excluded_jobs)


def _to_run_cost(run_id: int, run_attempt: int, aggregate: PRCostAggregate) -> RunCost:
    return RunCost(
        run_id=run_id,
        run_attempt=run_attempt,
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
