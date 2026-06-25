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
from typing import Any

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import PRCostSummary, WorkflowCost
from products.engineering_analytics.backend.logic.cost import PRCostAggregate, aggregate_pr_cost
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

_SELECT = """
    SELECT r.workflow_name, j.labels, j.duration_seconds
    FROM __JOBS_SOURCE__ AS j
    INNER JOIN __RUNS_SOURCE__ AS r ON j.run_id = r.id
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
