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

from products.engineering_analytics.backend.facade.contracts import PRCostSummary, WorkflowCost, WorkflowRunnerCost
from products.engineering_analytics.backend.logic.cost import PRCostAggregate, aggregate_pr_cost, runner_descriptor
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

_SELECT = """
    SELECT r.workflow_name, j.labels, j.duration_seconds
    FROM __JOBS_SOURCE__ AS j
    INNER JOIN __RUNS_SOURCE__ AS r ON j.run_id = r.id AND j.run_attempt = r.run_attempt
    WHERE r.pr_number = {pr_number} AND r.repo_owner = {repo_owner} AND r.repo_name = {repo_name}
"""

_EMPTY = PRCostSummary(
    jobs_available=False,
    billable_minutes=0.0,
    estimated_cost_usd=None,
    costed_jobs=0,
    unsettled_jobs=0,
    excluded_jobs=0,
    by_workflow=[],
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
    overall = aggregate_pr_cost((_parse_labels(labels), _duration(duration)) for _workflow, labels, duration in rows)

    by_workflow_jobs: dict[str, list[tuple[list[str], float | None]]] = defaultdict(list)
    for workflow, labels, duration in rows:
        by_workflow_jobs[workflow or ""].append((_parse_labels(labels), _duration(duration)))
    by_workflow = [
        _to_workflow_cost(workflow, aggregate_pr_cost(jobs)) for workflow, jobs in sorted(by_workflow_jobs.items())
    ]

    return PRCostSummary(
        jobs_available=True,
        billable_minutes=overall.billable_seconds / 60,
        estimated_cost_usd=overall.estimated_cost_usd,
        costed_jobs=overall.costed_jobs,
        unsettled_jobs=overall.unsettled_jobs,
        excluded_jobs=overall.excluded_jobs,
        by_workflow=by_workflow,
    )


# Pre-aggregated in SQL (per PR × runner-label combo) so the row count stays small — a raw per-job
# SELECT over every PR's jobs blows past HogQL's default row cap and silently truncates. Each group
# carries finished/elapsed/unfinished, which is expanded back into per-job tuples (cost is linear in
# elapsed) so the pure aggregate_pr_cost still produces the exact rollup.
_LIST_SELECT = """
    SELECT
        r.repo_owner, r.repo_name, r.pr_number, j.labels,
        countIf(j.duration_seconds IS NOT NULL) AS finished,
        sumIf(j.duration_seconds, j.duration_seconds IS NOT NULL) AS elapsed,
        countIf(j.duration_seconds IS NULL) AS unfinished
    FROM __JOBS_SOURCE__ AS j
    INNER JOIN __RUNS_SOURCE__ AS r ON j.run_id = r.id AND j.run_attempt = r.run_attempt
    WHERE r.pr_number > 0
    GROUP BY r.repo_owner, r.repo_name, r.pr_number, j.labels
    LIMIT 1000000
"""


def query_pr_list_costs(*, curated: CuratedGitHubSource) -> dict[tuple[str, str, int], PRCostAggregate]:
    """Per-PR billable cost across every attributed run, keyed by (repo_owner, repo_name, pr_number).

    Empty when the jobs source isn't synced. One grouped pass over jobs ⋈ runs so the PR list can show a
    cost/minutes column per row without a query per PR.
    """
    jobs_source = curated.jobs_source()
    if jobs_source is None:
        return {}
    sql = _LIST_SELECT.replace("__JOBS_SOURCE__", jobs_source).replace("__RUNS_SOURCE__", curated.run_source())
    response = curated.run(sql, query_type="engineering_analytics.pr_list_costs", placeholders={})
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
        sumIf(j.duration_seconds, j.duration_seconds IS NOT NULL) AS elapsed,
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


# Per-runner-tier cost for one workflow (single-workflow page "where the spend goes" breakdown).
_RUNNER_COST_SELECT = """
    SELECT
        j.labels,
        countIf(j.duration_seconds IS NOT NULL) AS finished,
        sumIf(j.duration_seconds, j.duration_seconds IS NOT NULL) AS elapsed,
        countIf(j.duration_seconds IS NULL) AS unfinished
    FROM __JOBS_SOURCE__ AS j
    INNER JOIN __RUNS_SOURCE__ AS r ON j.run_id = r.id AND j.run_attempt = r.run_attempt
    WHERE r.repo_owner = {repo_owner} AND r.repo_name = {repo_name} AND r.workflow_name = {workflow_name}
    GROUP BY j.labels
    LIMIT 1000000
"""


def query_workflow_runner_costs(
    *,
    curated: CuratedGitHubSource,
    repo_owner: str,
    repo_name: str,
    workflow_name: str,
) -> list[WorkflowRunnerCost]:
    """A workflow's CI cost broken down by runner tier, highest spend first. Empty when the jobs source
    isn't synced. Raw runner-label combos are folded into their display tier (via runner_descriptor)."""
    jobs_source = curated.jobs_source()
    if jobs_source is None:
        return []
    sql = _RUNNER_COST_SELECT.replace("__JOBS_SOURCE__", jobs_source).replace("__RUNS_SOURCE__", curated.run_source())
    response = curated.run(
        sql,
        query_type="engineering_analytics.workflow_runner_costs",
        placeholders={
            "repo_owner": ast.Constant(value=repo_owner),
            "repo_name": ast.Constant(value=repo_name),
            "workflow_name": ast.Constant(value=workflow_name),
        },
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
    elapsed, so the summed cost/minutes/counts are identical to costing each real job."""
    per = (elapsed_total / finished) if finished else 0.0
    return [(labels, per)] * finished + [(labels, None)] * unfinished


def _to_workflow_cost(workflow_name: str, aggregate: PRCostAggregate) -> WorkflowCost:
    return WorkflowCost(
        workflow_name=workflow_name,
        billable_minutes=aggregate.billable_seconds / 60,
        estimated_cost_usd=aggregate.estimated_cost_usd,
        costed_jobs=aggregate.costed_jobs,
        unsettled_jobs=aggregate.unsettled_jobs,
        excluded_jobs=aggregate.excluded_jobs,
    )


def _duration(value: Any) -> float | None:
    return float(value) if value is not None else None


def _parse_labels(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []
