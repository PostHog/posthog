"""HogQL assembly of a PR's estimated CI cost, summed over the jobs of all its runs.

Cost is job-level: a run fans into parallel jobs on different runner tiers, so per-PR cost is a sum
over jobs (see ``logic.cost``). This joins the optional jobs source (``_curated.jobs_source``) to the
runs source to bring each job's ``workflow_name`` alongside its ``labels`` / elapsed, then aggregates
in Python twice: once over all jobs (the whole-PR rollup) and once per workflow (the per-workflow cost
column). When the jobs source isn't synced, ``jobs_source()`` is None and this returns an empty summary
(``jobs_available=False``) so the UI hides the cost cards instead of erroring.
"""

import json
from collections import defaultdict
from datetime import datetime
from typing import Any

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import (
    PRCostSummary,
    RunCost,
    WorkflowCost,
    WorkflowRunnerCost,
)
from products.engineering_analytics.backend.logic.cost import PRCostAggregate, aggregate_pr_cost, runner_descriptor
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

# Pre-aggregated per (workflow, run, attempt, runner-label) — a raw per-job SELECT has no LIMIT, so HogQL
# caps it at DEFAULT_RETURNED_ROWS (100) and silently drops the rest, undercounting any PR with >100 jobs.
# Each group carries finished/elapsed/unfinished, expanded back into per-job tuples (cost is linear in
# elapsed) so the run- and workflow-level rollups stay exact. Same shape as the PR-list cost query.
_SELECT = """
    SELECT
        r.workflow_name, r.id AS run_id, r.run_attempt, j.labels,
        countIf(j.duration_seconds IS NOT NULL) AS finished,
        sumIf(greatest(j.duration_seconds, 0), j.duration_seconds IS NOT NULL) AS elapsed,
        countIf(j.duration_seconds IS NULL) AS unfinished
    FROM __JOBS_SOURCE__ AS j
    INNER JOIN __RUNS_SOURCE__ AS r ON j.run_id = r.id AND j.run_attempt = r.run_attempt
    WHERE r.pr_number = {pr_number} AND r.repo_owner = {repo_owner} AND r.repo_name = {repo_name}
    GROUP BY r.workflow_name, r.id, r.run_attempt, j.labels
    LIMIT 1000000
"""

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


def query_pr_cost(
    *,
    curated: CuratedGitHubSource,
    pr_number: int,
    repo_owner: str,
    repo_name: str,
) -> PRCostSummary:
    jobs_source = curated.jobs_source()
    if jobs_source is None:
        # The optional job-level source isn't synced for this team yet — no honest cost to report.
        return _EMPTY
    sql = _SELECT.replace("__JOBS_SOURCE__", jobs_source).replace("__RUNS_SOURCE__", curated.run_source())
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
    all_jobs: list[tuple[list[str], float | None]] = []
    by_workflow_jobs: dict[str, list[tuple[list[str], float | None]]] = defaultdict(list)
    by_run_jobs: dict[tuple[int, int], list[tuple[list[str], float | None]]] = defaultdict(list)
    for workflow, run_id, run_attempt, labels, finished, elapsed, unfinished in rows:
        jobs = _expand_jobs(_parse_labels(labels), int(finished or 0), float(elapsed or 0.0), int(unfinished or 0))
        all_jobs.extend(jobs)
        by_workflow_jobs[workflow or ""].extend(jobs)
        by_run_jobs[(int(run_id), int(run_attempt))].extend(jobs)
    overall = aggregate_pr_cost(all_jobs)
    by_workflow = [
        _to_workflow_cost(workflow, aggregate_pr_cost(jobs)) for workflow, jobs in sorted(by_workflow_jobs.items())
    ]
    by_run = [
        _to_run_cost(run_id, run_attempt, aggregate_pr_cost(jobs))
        for (run_id, run_attempt), jobs in sorted(by_run_jobs.items())
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


# Pre-aggregated in SQL (per PR × runner-label combo) so the row count stays small — a raw per-job
# SELECT over every PR's jobs blows past HogQL's default row cap and silently truncates. Each group
# carries finished/elapsed/unfinished, which is expanded back into per-job tuples (cost is linear in
# elapsed) so the pure aggregate_pr_cost still produces the exact rollup. Scoped to the PR numbers the
# list is actually showing so a team with deep CI history doesn't pay an all-time jobs×runs join per page.
_LIST_SELECT = """
    SELECT
        r.repo_owner, r.repo_name, r.pr_number, j.labels,
        countIf(j.duration_seconds IS NOT NULL) AS finished,
        sumIf(greatest(j.duration_seconds, 0), j.duration_seconds IS NOT NULL) AS elapsed,
        countIf(j.duration_seconds IS NULL) AS unfinished
    FROM __JOBS_SOURCE__ AS j
    INNER JOIN __RUNS_SOURCE__ AS r ON j.run_id = r.id AND j.run_attempt = r.run_attempt
    WHERE r.pr_number IN {pr_numbers}
    GROUP BY r.repo_owner, r.repo_name, r.pr_number, j.labels
    LIMIT 1000000
"""


def query_pr_list_costs(
    *, curated: CuratedGitHubSource, pr_numbers: list[int]
) -> dict[tuple[str, str, int], PRCostAggregate]:
    """Per-PR billable cost across the given PR numbers' runs, keyed by (repo_owner, repo_name, pr_number).

    Empty when the jobs source isn't synced or no PR numbers are given. One grouped pass over jobs ⋈ runs
    so the PR list can show a cost/minutes column per row without a query per PR; scoped to the visible PR
    numbers so the scan tracks the page, not the team's whole CI history.
    """
    jobs_source = curated.jobs_source()
    if jobs_source is None or not pr_numbers:
        return {}
    sql = _LIST_SELECT.replace("__JOBS_SOURCE__", jobs_source).replace("__RUNS_SOURCE__", curated.run_source())
    response = curated.run(
        sql,
        query_type="engineering_analytics.pr_list_costs",
        placeholders={"pr_numbers": ast.Constant(value=pr_numbers)},
    )
    by_pr: dict[tuple[str, str, int], list[tuple[list[str], float | None]]] = defaultdict(list)
    for repo_owner, repo_name, pr_number, labels, finished, elapsed, unfinished in response.results or []:
        by_pr[(repo_owner, repo_name, int(pr_number))].extend(
            _expand_jobs(_parse_labels(labels), int(finished or 0), float(elapsed or 0.0), int(unfinished or 0))
        )
    return {key: aggregate_pr_cost(jobs) for key, jobs in by_pr.items()}


# Per-workflow billable cost over a window (Workflows tab). Same grouped+expand shape as the PR list,
# but keyed by workflow_name and filtered by the run window + optional branch.
_WINDOW_COST_SELECT = """
    SELECT
        r.workflow_name, j.labels,
        countIf(j.duration_seconds IS NOT NULL) AS finished,
        sumIf(greatest(j.duration_seconds, 0), j.duration_seconds IS NOT NULL) AS elapsed,
        countIf(j.duration_seconds IS NULL) AS unfinished
    FROM __JOBS_SOURCE__ AS j
    INNER JOIN __RUNS_SOURCE__ AS r ON j.run_id = r.id AND j.run_attempt = r.run_attempt
    WHERE r.run_started_at >= {date_from} __DATE_TO__ __BRANCH__
    GROUP BY r.workflow_name, j.labels
    LIMIT 1000000
"""


def query_workflow_window_costs(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    branch: str | None,
) -> dict[str, PRCostAggregate]:
    """Per-workflow billable cost over [date_from, date_to] (optional branch), keyed by workflow_name.

    Empty when the jobs source isn't synced. Mirrors the PR-list cost: grouped per workflow×label in SQL,
    expanded back through aggregate_pr_cost.
    """
    jobs_source = curated.jobs_source()
    if jobs_source is None:
        return {}
    branch = branch.strip() if branch else None
    placeholders: dict[str, ast.Expr] = {"date_from": ast.Constant(value=date_from)}
    date_to_clause = ""
    if date_to is not None:
        date_to_clause = "AND r.run_started_at <= {date_to}"
        placeholders["date_to"] = ast.Constant(value=date_to)
    branch_clause = ""
    if branch:
        branch_clause = "AND r.head_branch = {branch}"
        placeholders["branch"] = ast.Constant(value=branch)
    sql = (
        _WINDOW_COST_SELECT.replace("__JOBS_SOURCE__", jobs_source)
        .replace("__RUNS_SOURCE__", curated.run_source())
        .replace("__DATE_TO__", date_to_clause)
        .replace("__BRANCH__", branch_clause)
    )
    response = curated.run(sql, query_type="engineering_analytics.workflow_window_costs", placeholders=placeholders)
    by_workflow: dict[str, list[tuple[list[str], float | None]]] = defaultdict(list)
    for workflow_name, labels, finished, elapsed, unfinished in response.results or []:
        by_workflow[workflow_name or ""].extend(
            _expand_jobs(_parse_labels(labels), int(finished or 0), float(elapsed or 0.0), int(unfinished or 0))
        )
    return {workflow: aggregate_pr_cost(jobs) for workflow, jobs in by_workflow.items()}


# One author's CI spend split by workflow (the author page's "where their CI minutes go"). Runs are
# attributed to the author through their PRs, keyed on (repo_owner, repo_name, pr_number) — never
# pr_number alone, since PR numbers restart per repo (SPEC §7). Windowed on the run start so the figure
# answers "spend over [window]", never an unbounded all-time.
_AUTHOR_WORKFLOW_SELECT = """
    SELECT
        r.workflow_name, j.labels,
        countIf(j.duration_seconds IS NOT NULL) AS finished,
        sumIf(greatest(j.duration_seconds, 0), j.duration_seconds IS NOT NULL) AS elapsed,
        countIf(j.duration_seconds IS NULL) AS unfinished
    FROM __JOBS_SOURCE__ AS j
    INNER JOIN __RUNS_SOURCE__ AS r ON j.run_id = r.id AND j.run_attempt = r.run_attempt
    INNER JOIN (
            SELECT DISTINCT repo_owner, repo_name, number FROM __PR_SOURCE__ WHERE author_handle = {author}
        ) AS ap ON r.repo_owner = ap.repo_owner AND r.repo_name = ap.repo_name AND r.pr_number = ap.number
    WHERE r.run_started_at >= {date_from} __DATE_TO__
    GROUP BY r.workflow_name, j.labels
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

    Empty when the jobs source isn't synced. Same grouped+expand shape as the other cost queries;
    the author→runs link goes through their PR numbers (the one attribution rule, SPEC §7).
    """
    jobs_source = curated.jobs_source()
    if jobs_source is None:
        return []
    placeholders: dict[str, ast.Expr] = {
        "author": ast.Constant(value=author),
        "date_from": ast.Constant(value=date_from),
    }
    date_to_clause = ""
    if date_to is not None:
        date_to_clause = "AND r.run_started_at <= {date_to}"
        placeholders["date_to"] = ast.Constant(value=date_to)
    sql = (
        _AUTHOR_WORKFLOW_SELECT.replace("__JOBS_SOURCE__", jobs_source)
        .replace("__RUNS_SOURCE__", curated.run_source())
        .replace("__PR_SOURCE__", curated.pr_source())
        .replace("__DATE_TO__", date_to_clause)
    )
    response = curated.run(sql, query_type="engineering_analytics.author_workflow_costs", placeholders=placeholders)
    by_workflow: dict[str, list[tuple[list[str], float | None]]] = defaultdict(list)
    for workflow_name, labels, finished, elapsed, unfinished in response.results or []:
        by_workflow[workflow_name or ""].extend(
            _expand_jobs(_parse_labels(labels), int(finished or 0), float(elapsed or 0.0), int(unfinished or 0))
        )
    costs = [_to_workflow_cost(workflow, aggregate_pr_cost(jobs)) for workflow, jobs in by_workflow.items()]
    return sorted(costs, key=lambda cost: (cost.estimated_cost_usd or 0.0, cost.billable_minutes), reverse=True)


# The window-cost shape twice over — the current window and the equal-length one before it — as
# per-window conditional aggregates on one jobs⋈runs scan, so the repo hub's delta doesn't pay the
# (largest-table) join twice. Window predicates mirror the two separate calls exactly.
_WINDOW_COST_WITH_PREV_SELECT = """
    SELECT
        r.workflow_name, j.labels,
        countIf(j.duration_seconds IS NOT NULL AND __CUR__) AS finished,
        sumIf(greatest(j.duration_seconds, 0), j.duration_seconds IS NOT NULL AND __CUR__) AS elapsed,
        countIf(j.duration_seconds IS NULL AND __CUR__) AS unfinished,
        countIf(j.duration_seconds IS NOT NULL AND __PREV__) AS finished_prev,
        sumIf(greatest(j.duration_seconds, 0), j.duration_seconds IS NOT NULL AND __PREV__) AS elapsed_prev,
        countIf(j.duration_seconds IS NULL AND __PREV__) AS unfinished_prev
    FROM __JOBS_SOURCE__ AS j
    INNER JOIN __RUNS_SOURCE__ AS r ON j.run_id = r.id AND j.run_attempt = r.run_attempt
    WHERE r.run_started_at >= {prev_from} __DATE_TO__
    GROUP BY r.workflow_name, j.labels
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
    """
    jobs_source = curated.jobs_source()
    if jobs_source is None:
        return {}, {}
    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=date_from),
        "prev_from": ast.Constant(value=prev_from),
    }
    cur = "(r.run_started_at >= {date_from}" + (" AND r.run_started_at <= {date_to})" if date_to else ")")
    prev = "(r.run_started_at >= {prev_from} AND r.run_started_at <= {date_from})"
    date_to_clause = ""
    if date_to is not None:
        date_to_clause = "AND r.run_started_at <= {date_to}"
        placeholders["date_to"] = ast.Constant(value=date_to)
    sql = (
        _WINDOW_COST_WITH_PREV_SELECT.replace("__JOBS_SOURCE__", jobs_source)
        .replace("__RUNS_SOURCE__", curated.run_source())
        .replace("__CUR__", cur)
        .replace("__PREV__", prev)
        .replace("__DATE_TO__", date_to_clause)
    )
    response = curated.run(
        sql, query_type="engineering_analytics.workflow_window_costs_with_prev", placeholders=placeholders
    )
    by_workflow_cur: dict[str, list[tuple[list[str], float | None]]] = defaultdict(list)
    by_workflow_prev: dict[str, list[tuple[list[str], float | None]]] = defaultdict(list)
    for workflow_name, labels, finished, elapsed, unfinished, finished_prev, elapsed_prev, unfinished_prev in (
        response.results or []
    ):
        parsed = _parse_labels(labels)
        by_workflow_cur[workflow_name or ""].extend(
            _expand_jobs(parsed, int(finished or 0), float(elapsed or 0.0), int(unfinished or 0))
        )
        by_workflow_prev[workflow_name or ""].extend(
            _expand_jobs(parsed, int(finished_prev or 0), float(elapsed_prev or 0.0), int(unfinished_prev or 0))
        )
    return (
        {workflow: aggregate_pr_cost(jobs) for workflow, jobs in by_workflow_cur.items() if jobs},
        {workflow: aggregate_pr_cost(jobs) for workflow, jobs in by_workflow_prev.items() if jobs},
    )


# Per-runner-tier cost for one workflow (single-workflow page "where the spend goes" breakdown), scoped
# to the page's run window (and optional branch) so the figure always answers "spend over [window]",
# never an unbounded all-time.
_RUNNER_COST_SELECT = """
    SELECT
        j.labels,
        countIf(j.duration_seconds IS NOT NULL) AS finished,
        sumIf(greatest(j.duration_seconds, 0), j.duration_seconds IS NOT NULL) AS elapsed,
        countIf(j.duration_seconds IS NULL) AS unfinished
    FROM __JOBS_SOURCE__ AS j
    INNER JOIN __RUNS_SOURCE__ AS r ON j.run_id = r.id AND j.run_attempt = r.run_attempt
    WHERE r.repo_owner = {repo_owner} AND r.repo_name = {repo_name} AND r.workflow_name = {workflow_name}
        AND r.run_started_at >= {date_from} __DATE_TO__ __BRANCH__
    GROUP BY j.labels
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
    highest spend first. Empty when the jobs source isn't synced. Raw runner-label combos are folded
    into their display tier (via runner_descriptor)."""
    jobs_source = curated.jobs_source()
    if jobs_source is None:
        return []
    placeholders: dict[str, ast.Expr] = {
        "repo_owner": ast.Constant(value=repo_owner),
        "repo_name": ast.Constant(value=repo_name),
        "workflow_name": ast.Constant(value=workflow_name),
        "date_from": ast.Constant(value=date_from),
    }
    date_to_clause = ""
    if date_to is not None:
        date_to_clause = "AND r.run_started_at <= {date_to}"
        placeholders["date_to"] = ast.Constant(value=date_to)
    # An empty/whitespace branch is "no filter", not a literal match on '' — mirrors workflow_health.
    branch = branch.strip() if branch else None
    branch_clause = ""
    if branch:
        branch_clause = "AND r.head_branch = {branch}"
        placeholders["branch"] = ast.Constant(value=branch)
    sql = (
        _RUNNER_COST_SELECT.replace("__JOBS_SOURCE__", jobs_source)
        .replace("__RUNS_SOURCE__", curated.run_source())
        .replace("__DATE_TO__", date_to_clause)
        .replace("__BRANCH__", branch_clause)
    )
    response = curated.run(
        sql,
        query_type="engineering_analytics.workflow_runner_costs",
        placeholders=placeholders,
    )
    by_tier: dict[tuple[str, str], list[tuple[list[str], float | None]]] = defaultdict(list)
    for labels_raw, finished, elapsed, unfinished in response.results or []:
        labels = _parse_labels(labels_raw)
        by_tier[runner_descriptor(labels)].extend(
            _expand_jobs(labels, int(finished or 0), float(elapsed or 0.0), int(unfinished or 0))
        )
    costs = []
    for (provider, label), jobs in by_tier.items():
        aggregate = aggregate_pr_cost(jobs)
        costs.append(
            WorkflowRunnerCost(
                provider=provider,
                runner_label=label,
                job_count=len(jobs),
                billable_minutes=aggregate.billable_seconds / 60,
                estimated_cost_usd=aggregate.estimated_cost_usd,
            )
        )
    return sorted(costs, key=lambda cost: (cost.estimated_cost_usd or 0.0, cost.billable_minutes), reverse=True)


def _expand_jobs(
    labels: list[str], finished: int, elapsed_total: float, unfinished: int
) -> list[tuple[list[str], float | None]]:
    """Re-expand a (labels, finished, elapsed_total, unfinished) group into per-job (labels, elapsed)
    tuples for aggregate_pr_cost. Elapsed is split evenly across finished jobs — cost is linear in
    elapsed, so the summed cost/minutes/counts are identical to costing each real job. The SQL sums
    ``greatest(duration_seconds, 0)`` so a single clock-skewed negative duration can't cancel its
    group-mates' elapsed before the split — matching aggregate_pr_cost's per-job ``max(0, elapsed)``."""
    per = (elapsed_total / finished) if finished else 0.0
    return [(labels, per)] * finished + [(labels, None)] * unfinished


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


def _parse_labels(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []
