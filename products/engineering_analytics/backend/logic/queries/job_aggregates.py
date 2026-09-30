"""Curated query: per-job aggregates for one workflow over a window.

The workflow page's jobs table: one row per de-sharded job name (the matrix "(G/N)"
suffix stripped in SQL with the same rule the frontend's jobGroups uses), with queue
p50 (created -> started, where runner-capacity problems hide), duration percentiles
(successful jobs only — the shared DURATION_PERCENTILE_CONDITION population),
failure rate, retry pressure, run share (conditional jobs skip — "runs in 31% of
runs"), and billable cost, all from one scan of the per-job cost source. The
run-share denominator comes from a cheap runs count.

Unexpanded ``${{ matrix.* }}`` template names (skipped matrices) are collapsed for
grouping the same way the frontend does.
"""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import WorkflowHealthRunScope, WorkflowJobAggregate
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource, opt_float
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    DURATION_PERCENTILE_CONDITION,
    branch_filter_clause,
    cost_run_scope_filter_clause,
    date_to_filter_clause,
    failure_rate_expr,
    run_scope_filter_clause,
    run_windowed_job_created_floor_constant,
)

_LIMIT = 200

# A skipped job is stamped started_at = created_at, so it never queued. `conclusion` is Nullable and
# NULL != 'skipped' is NULL, which quantileIf drops; the ifNull keeps still-running jobs in the sample.
_QUEUED_JOB_CONDITION = "ifNull(conclusion, '') != 'skipped'"

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


# One scan of the shared per-job cost source. It joins each job to its run, so the run-scope filters can
# read the run's attributes, and the job stats and the billable cost read the same rows.
_AGGREGATE_SELECT = f"""
    SELECT
        {_job_name_expr("job_name")} AS job_group,
        count() AS job_count,
        uniq(job_name) AS shard_count,
        uniq(run_id) AS runs_in,
        quantileIf(0.5)(queue_seconds, {_QUEUED_JOB_CONDITION}) AS queue_p50_seconds,
        quantileIf(0.5)(duration_seconds, {DURATION_PERCENTILE_CONDITION}) AS p50_seconds,
        quantileIf(0.95)(duration_seconds, {DURATION_PERCENTILE_CONDITION}) AS p95_seconds,
        -- Jobs without a verdict (skipped, cancelled, neutral) stay in job_count but not in the rate.
        {failure_rate_expr()} AS failure_rate,
        countIf(run_attempt > 1) AS retry_job_count,
        sum(ifNull(billable_seconds, 0)) AS billable_seconds,
        sumIf(estimated_cost_usd, estimated_cost_usd IS NOT NULL) AS cost_sum,
        countIf(estimated_cost_usd IS NOT NULL) AS costed_jobs
    FROM __COST_SOURCE__ AS c
    -- NOT is_rerun_copy: "Re-run failed jobs" re-lists every already-passed job under the new attempt
    -- with the earlier attempt's timestamps. Counting those would double every duration sample and
    -- report retry pressure for jobs nobody retried. A copy carries no cost, so the filter leaves the cost as is.
    WHERE NOT is_rerun_copy
        AND workflow_name = {{workflow_name}} AND created_at >= {{date_from}} __DATE_TO__ __BRANCH__
        __COST_RUN_SCOPE__
    GROUP BY job_group
    ORDER BY job_count DESC
    LIMIT {_LIMIT}
"""

_RUN_COUNT_SELECT = """
    SELECT count() AS total_runs
    FROM __RUNS_SOURCE__ AS r
    WHERE workflow_name = {workflow_name} AND run_started_at >= {date_from}
        __RUNS_DATE_TO__ __RUNS_BRANCH__ __RUNS_RUN_SCOPE__
"""


def query_job_aggregates(
    *,
    curated: CuratedGitHubSource,
    workflow_name: str,
    date_from: datetime,
    date_to: datetime | None,
    branch: str | None,
    run_scope: WorkflowHealthRunScope = WorkflowHealthRunScope.ALL,
) -> list[WorkflowJobAggregate]:
    # The query windows the job's OWN created_at, but it EXCLUDES re-run copies, and a copy is only
    # recognisable while its original attempt is still in the scan: a re-run a day or more after the
    # original push would otherwise pull the copy inside the window, drop the original below a tight
    # floor, and count the copy as an execution. So take the wide floor, same as the cost surfaces.
    cost_source = curated.job_cost_source(created_floor=True)
    if cost_source is None:
        return []

    branch = branch.strip() if branch else None
    placeholders: dict[str, ast.Expr] = {
        "workflow_name": ast.Constant(value=workflow_name),
        "date_from": ast.Constant(value=date_from),
        "job_created_floor": run_windowed_job_created_floor_constant(date_from),
    }
    # Each clause registers its own placeholder. The job template windows the job's created_at, and the
    # run-count template the run's run_started_at.
    date_to_clause = date_to_filter_clause(date_to, placeholders, column="created_at")
    runs_date_to_clause = date_to_filter_clause(date_to, placeholders, column="run_started_at")
    branch_clause = branch_filter_clause(branch, placeholders, column="head_branch")

    def fill(template: str) -> str:
        return (
            template.replace("__COST_SOURCE__", cost_source)
            .replace("__COST_RUN_SCOPE__", cost_run_scope_filter_clause(run_scope))
            .replace("__RUNS_RUN_SCOPE__", run_scope_filter_clause(run_scope))
            .replace("__RUNS_SOURCE__", curated.run_source())
            .replace("__DATE_TO__", date_to_clause)
            .replace("__RUNS_DATE_TO__", runs_date_to_clause)
            .replace("__BRANCH__", branch_clause)
            .replace("__RUNS_BRANCH__", branch_clause)
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
        billable_seconds,
        cost_sum,
        costed_jobs,
    ) in response.results:
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
                # No costed job (every instance github-hosted, non-Linux, or still queued) leaves the cost
                # unknown rather than billing a not-yet-finished or non-billable job as $0.
                billable_minutes=float(billable_seconds or 0.0) / 60 if costed_jobs else None,
                estimated_cost_usd=float(cost_sum or 0.0) if costed_jobs else None,
            )
        )
    return items
