"""Curated query: per-job aggregates for one workflow over a window.

The workflow page's jobs table: one row per de-sharded job name (the matrix "(G/N)"
suffix stripped in SQL with the same rule the frontend's jobGroups uses), with queue
p50 (created -> started, where runner-capacity problems hide), duration percentiles,
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
from products.engineering_analytics.backend.logic.cost import estimate_job_cost_usd
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource, opt_float
from products.engineering_analytics.backend.logic.queries.pr_cost import _parse_labels

_LIMIT = 200

# De-shard + de-template in SQL so grouping happens server-side over millions of job rows.
# Mirrors jobGroups.stripShardSuffix / collapseTemplates on the frontend and
# master_failures.strip_shard_suffix in Python — keep the three in sync.
_JOB_NAME = (
    "replaceRegexpOne(replaceRegexpAll(name, '\\\\$\\\\{\\\\{[^}]*\\\\}\\\\}', '…'),"
    " '\\\\s*\\\\((\\\\d+)/(\\\\d+)\\\\)(\\\\))?$', '\\\\3')"
)

_AGGREGATE_SELECT = f"""
    SELECT
        {_JOB_NAME} AS job_name,
        count() AS job_count,
        uniq(name) AS shard_count,
        uniq(run_id) AS runs_in,
        quantile(0.5)(queue_seconds) AS queue_p50_seconds,
        quantileIf(0.5)(duration_seconds, status = 'completed') AS p50_seconds,
        quantileIf(0.95)(duration_seconds, status = 'completed') AS p95_seconds,
        countIf(conclusion IN ('failure', 'timed_out')) / nullIf(countIf(status = 'completed'), 0) AS failure_rate,
        countIf(run_attempt > 1) AS retry_job_count
    FROM __JOBS_SOURCE__ AS j
    WHERE workflow_name = {{workflow_name}} AND created_at >= {{date_from}} __DATE_TO__ __BRANCH__
    GROUP BY job_name
    ORDER BY job_count DESC
    LIMIT {_LIMIT}
"""

_COST_SELECT = f"""
    SELECT
        {_JOB_NAME} AS job_name,
        labels,
        sumIf(greatest(duration_seconds, 0), duration_seconds IS NOT NULL) AS elapsed_seconds,
        countIf(duration_seconds IS NOT NULL) AS settled_jobs
    FROM __JOBS_SOURCE__ AS j
    WHERE workflow_name = {{workflow_name}} AND created_at >= {{date_from}} __DATE_TO__ __BRANCH__
    GROUP BY job_name, labels
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
    if jobs_source is None:
        return []

    branch = branch.strip() if branch else None
    placeholders: dict[str, ast.Expr] = {
        "workflow_name": ast.Constant(value=workflow_name),
        "date_from": ast.Constant(value=date_from),
    }
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)
    if branch:
        placeholders["branch"] = ast.Constant(value=branch)

    def fill(template: str) -> str:
        return (
            template.replace("__JOBS_SOURCE__", jobs_source)
            .replace("__RUNS_SOURCE__", curated.run_source())
            .replace("__DATE_TO__", "AND created_at <= {date_to}" if date_to is not None else "")
            .replace("__RUNS_DATE_TO__", "AND run_started_at <= {date_to}" if date_to is not None else "")
            .replace("__BRANCH__", "AND head_branch = {branch}" if branch else "")
            .replace("__RUNS_BRANCH__", "AND head_branch = {branch}" if branch else "")
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

    # Billable cost per job name, folded over its (labels) groups via the shared cost model.
    cost_response = curated.run(
        fill(_COST_SELECT), query_type="engineering_analytics.job_aggregates_cost", placeholders=placeholders
    )
    billable_by_job: dict[str, tuple[float, float]] = {}
    for job_name, labels_raw, elapsed_seconds, settled_jobs in cost_response.results or []:
        # An all-unsettled group (every instance still queued/running) sums to 0 elapsed — pass None
        # so its cost stays unknown instead of billing a not-yet-finished job as $0.
        elapsed = float(elapsed_seconds or 0.0) if settled_jobs else None
        cost = estimate_job_cost_usd(_parse_labels(labels_raw), elapsed)
        if cost is None:
            continue
        seconds, usd = billable_by_job.get(job_name, (0.0, 0.0))
        billable_by_job[job_name] = (seconds + (elapsed or 0.0), usd + cost)

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
