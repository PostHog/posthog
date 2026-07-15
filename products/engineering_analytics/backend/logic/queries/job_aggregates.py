"""Curated query: per-job aggregates for one workflow over a window.

The workflow page's jobs table: one row per de-sharded job name (the matrix "(G/N)"
suffix stripped in SQL with the same rule the frontend's jobGroups uses), with queue
p50 (created -> started, where runner-capacity problems hide), duration percentiles
(successful jobs only — the shared DURATION_PERCENTILE_CONDITION population),
failure rate, retry pressure, run share (conditional jobs skip — "runs in 31% of
runs"), and billable cost. Jobs carry ``workflow_name`` / ``head_branch`` /
``created_at`` directly, so no join to the runs table is needed; the run-share
denominator comes from a cheap runs count.

Unexpanded ``${{ matrix.* }}`` template names (skipped matrices) are collapsed for
grouping the same way the frontend does.
"""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import WorkflowJobAggregate
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource, opt_float
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    DURATION_PERCENTILE_CONDITION,
    branch_filter_clause,
    date_to_filter_clause,
)

_LIMIT = 200

# De-shard + de-template in SQL so grouping happens server-side over millions of job rows.
# Mirrors jobGroups.stripShardSuffix / collapseTemplates on the frontend and
# master_failures.strip_shard_suffix in Python — keep the three in sync.
_JOB_NAME_TEMPLATE = (
    "replaceRegexpOne(replaceRegexpAll(__NAME__, '\\\\$\\\\{\\\\{[^}]*\\\\}\\\\}', '…'),"
    " '\\\\s*\\\\((\\\\d+)/(\\\\d+)\\\\)(\\\\))?$', '\\\\3')"
)


def _job_name_expr(column: str) -> str:
    """The de-shard/de-template expression over ``column`` — the raw ``name`` in the jobs source, or
    the cost source's ``job_name`` (which is that same ``name``, renamed by the cost builder)."""
    return _JOB_NAME_TEMPLATE.replace("__NAME__", column)


_AGGREGATE_SELECT = f"""
    SELECT
        {_job_name_expr("name")} AS job_name,
        count() AS job_count,
        uniq(name) AS shard_count,
        uniq(run_id) AS runs_in,
        quantile(0.5)(queue_seconds) AS queue_p50_seconds,
        quantileIf(0.5)(duration_seconds, {DURATION_PERCENTILE_CONDITION}) AS p50_seconds,
        quantileIf(0.95)(duration_seconds, {DURATION_PERCENTILE_CONDITION}) AS p95_seconds,
        countIf(conclusion IN ('failure', 'timed_out')) / nullIf(countIf(status = 'completed'), 0) AS failure_rate,
        countIf(run_attempt > 1) AS retry_job_count
    FROM __JOBS_SOURCE__ AS j
    WHERE workflow_name = {{workflow_name}} AND created_at >= {{date_from}} __DATE_TO__ __BRANCH__
    GROUP BY job_name
    ORDER BY job_count DESC
    LIMIT {_LIMIT}
"""

# Billable cost per de-sharded job name, read straight off the shared per-job cost source (the same
# rendered model as engineering_analytics_job_costs) so cost is computed once in SQL, not folded from
# raw labels in Python. Cost columns are per-job on that source, so summing them per job name is exact.
_COST_SELECT = f"""
    SELECT
        {_job_name_expr("job_name")} AS job_name,
        sum(ifNull(billable_seconds, 0)) AS billable_seconds,
        sumIf(estimated_cost_usd, estimated_cost_usd IS NOT NULL) AS cost_sum,
        countIf(estimated_cost_usd IS NOT NULL) AS costed_jobs
    FROM __COST_SOURCE__ AS c
    WHERE workflow_name = {{workflow_name}} AND created_at >= {{date_from}} __DATE_TO__ __BRANCH__
    GROUP BY job_name
"""

_RUN_COUNT_SELECT = """
    SELECT count() AS total_runs
    FROM __RUNS_SOURCE__ AS r
    WHERE workflow_name = {workflow_name} AND run_started_at >= {date_from} __RUNS_DATE_TO__ __RUNS_BRANCH__
"""


def query_job_aggregates(
    *,
    curated: CuratedGitHubSource,
    workflow_name: str,
    date_from: datetime,
    date_to: datetime | None,
    branch: str | None,
) -> list[WorkflowJobAggregate]:
    jobs_source = curated.jobs_source()
    cost_source = curated.job_cost_source()
    if jobs_source is None or cost_source is None:
        return []

    branch = branch.strip() if branch else None
    placeholders: dict[str, ast.Expr] = {
        "workflow_name": ast.Constant(value=workflow_name),
        "date_from": ast.Constant(value=date_from),
    }
    # Shared filter clauses (each registers its own placeholder). The jobs/cost templates window and
    # branch-filter on the per-job created_at + head_branch; the run-count template reads the run
    # source's run_started_at (its head_branch is still the per-run branch).
    date_to_clause = date_to_filter_clause(date_to, placeholders, column="created_at")
    runs_date_to_clause = date_to_filter_clause(date_to, placeholders, column="run_started_at")
    branch_clause = branch_filter_clause(branch, placeholders, column="head_branch")
    runs_branch_clause = branch_filter_clause(branch, placeholders, column="head_branch")

    def fill(template: str) -> str:
        return (
            template.replace("__JOBS_SOURCE__", jobs_source)
            .replace("__COST_SOURCE__", cost_source)
            .replace("__RUNS_SOURCE__", curated.run_source())
            .replace("__DATE_TO__", date_to_clause)
            .replace("__RUNS_DATE_TO__", runs_date_to_clause)
            .replace("__BRANCH__", branch_clause)
            .replace("__RUNS_BRANCH__", runs_branch_clause)
        )

    response = curated.run(
        fill(_AGGREGATE_SELECT), query_type="engineering_analytics.job_aggregates", placeholders=placeholders
    )
    if not response.results:
        return []

    run_count_response = curated.run(
        fill(_RUN_COUNT_SELECT), query_type="engineering_analytics.job_aggregates_runs", placeholders=placeholders
    )
    total_runs = run_count_response.results[0][0] if run_count_response.results else 0

    # Billable cost per de-sharded job name, summed in SQL over the shared per-job cost source.
    cost_response = curated.run(
        fill(_COST_SELECT), query_type="engineering_analytics.job_aggregates_cost", placeholders=placeholders
    )
    billable_by_job: dict[str, tuple[float, float]] = {}
    for job_name, billable_seconds, cost_sum, costed_jobs in cost_response.results or []:
        # No costed job (every instance github-hosted, non-Linux, or still queued) → leave the cost
        # unknown rather than billing a not-yet-finished/non-billable job as $0.
        if not costed_jobs:
            continue
        billable_by_job[job_name] = (float(billable_seconds or 0.0), float(cost_sum or 0.0))

    items: list[WorkflowJobAggregate] = []
    for (
        job_name,
        job_count,
        shard_count,
        runs_in,
        queue_p50_seconds,
        p50_seconds,
        p95_seconds,
        failure_rate,
        retry_job_count,
    ) in response.results:
        billable = billable_by_job.get(job_name)
        items.append(
            WorkflowJobAggregate(
                job_name=job_name,
                job_count=job_count,
                shard_count=shard_count,
                runs_in=runs_in,
                run_share=(runs_in / total_runs) if total_runs else None,
                queue_p50_seconds=opt_float(queue_p50_seconds),
                p50_seconds=opt_float(p50_seconds),
                p95_seconds=opt_float(p95_seconds),
                failure_rate=opt_float(failure_rate),
                retry_job_count=retry_job_count,
                billable_minutes=billable[0] / 60 if billable else None,
                estimated_cost_usd=billable[1] if billable else None,
            )
        )
    return items
