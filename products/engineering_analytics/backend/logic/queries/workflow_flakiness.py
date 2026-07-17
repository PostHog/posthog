"""Immutable workflow-job observations that failed and passed on a later attempt."""

from dataclasses import dataclass
from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

# A job that "failed" in under this many seconds did no real CI work. The shape is a required-check
# aggregator (`needs: [...]` with `if: always()`) reporting a dependency's conclusion, so its
# fail-then-pass merely echoes the job it gates: counting it emits a second observation for every
# real flake and buries the real one under gate noise. Measured against PostHog/posthog, every
# `* Pass` aggregator settles in 3-5s (p90 <= 7s) while real jobs run 60s+, so the boundary is wide.
# Mirrors NO_OP_RUN_MAX_SECONDS in `_workflow_filters` (which flags the same shape at run level).
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
    WHERE j.created_at >= {date_from} AND j.head_sha != ''
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
) -> list[FlakyJobRun]:
    jobs_source = curated.jobs_source()
    if jobs_source is None:
        return []
    response = curated.run(
        _SELECT.replace("__JOBS_SOURCE__", jobs_source).replace("__RUNS_SOURCE__", curated.run_source()),
        query_type="engineering_analytics.workflow_flakiness",
        placeholders={
            "date_from": ast.Constant(value=date_from),
            "min_failed_duration_seconds": ast.Constant(value=min_failed_duration_seconds),
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
