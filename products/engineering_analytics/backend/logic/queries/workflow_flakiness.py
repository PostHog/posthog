"""Immutable workflow-job observations that failed and passed on a later attempt."""

from dataclasses import dataclass
from datetime import datetime

from posthog.hogql import ast

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import run_started_floor_constant

# A job that failed in under this many seconds did no real work: it's a required-check aggregator
# echoing a dependency's failure, which double-counts every real flake. Measured on PostHog/posthog,
# aggregators settle in 3-5s and real jobs run 60s+. Run-level twin: NO_OP_RUN_MAX_SECONDS.
NO_OP_JOB_MAX_SECONDS = 10

_SELECT = """
    SELECT
        r.repo_owner,
        r.repo_name,
        j.workflow_name,
        j.name AS job_name,
        j.run_id,
        j.head_sha,
        minIf(j.run_attempt, j.conclusion IN ('failure', 'timed_out')) AS failed_attempt,
        maxIf(j.run_attempt, j.conclusion = 'success') AS passed_attempt,
        maxIf(j.duration_seconds, j.conclusion IN ('failure', 'timed_out')) AS failed_duration_seconds
    FROM __JOBS_SOURCE__ AS j
    INNER JOIN __RUNS_SOURCE__ AS r ON r.id = j.run_id
    -- created_at_raw is the unparsed string the scan can prune on; the parsed j.created_at filter
    -- alone can't push down, so both floors keep the sweep off a full jobs+runs scan each hour.
    WHERE j.created_at >= {date_from} AND j.created_at_raw >= {job_created_floor} AND j.head_sha != ''
    GROUP BY r.repo_owner, r.repo_name, j.workflow_name, j.name, j.run_id, j.head_sha
    HAVING failed_attempt > 0
       AND passed_attempt > failed_attempt
       AND failed_duration_seconds >= {min_failed_duration_seconds}
    ORDER BY j.run_id DESC
    LIMIT 1000
"""


@dataclass(frozen=True)
class FlakyJobRun:
    repo_owner: str
    repo_name: str
    workflow_name: str
    job_name: str
    run_id: int
    head_sha: str
    failed_attempt: int
    passed_attempt: int


def query_workflow_flakiness(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    min_failed_duration_seconds: int = NO_OP_JOB_MAX_SECONDS,
    workload: Workload = Workload.DEFAULT,
) -> list[FlakyJobRun]:
    jobs_source = curated.jobs_source()
    if jobs_source is None:
        return []
    response = curated.run(
        _SELECT.replace("__JOBS_SOURCE__", jobs_source).replace(
            "__RUNS_SOURCE__", curated.run_source(started_floor=True)
        ),
        query_type="engineering_analytics.workflow_flakiness",
        workload=workload,
        placeholders={
            "date_from": ast.Constant(value=date_from),
            "min_failed_duration_seconds": ast.Constant(value=min_failed_duration_seconds),
            # Same date-only floor for both tables: prunes the runs subquery (run_started_floor) and
            # the jobs scan (job_created_floor via created_at_raw).
            "run_started_floor": run_started_floor_constant(date_from),
            "job_created_floor": run_started_floor_constant(date_from),
        },
    )
    return [
        FlakyJobRun(
            repo_owner=repo_owner,
            repo_name=repo_name,
            workflow_name=workflow_name,
            job_name=job_name,
            run_id=int(run_id),
            head_sha=head_sha,
            failed_attempt=int(failed_attempt),
            passed_attempt=int(passed_attempt),
        )
        for repo_owner, repo_name, workflow_name, job_name, run_id, head_sha, failed_attempt, passed_attempt, _ in (
            response.results or []
        )
    ]
