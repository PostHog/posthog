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

# Jobs whose failure is a deliberate signal rather than nondeterminism. They commit an artifact
# (updated snapshots, a completed Visual Review run) and then exit non-zero so auto-merge is blocked
# until a human reviews what changed. A rerun passes because the artifact is already in place, so
# each one produces a guaranteed fail-then-pass pair on a single run, which is the exact shape this
# query reads as flakiness. They do real work, so NO_OP_JOB_MAX_SECONDS above cannot catch them.
#
# Nothing in the landed job data separates a deliberate `exit 1` from a genuine infra failure in the
# same job, so excluding them by name drops both: a real flake inside one of these jobs, such as a
# dead checkout step or a runner timeout, stays invisible to the flaky-check signal. That is the
# accepted cost. Telling the two apart would mean parsing the `steps` JSON, which no query reads.
BY_DESIGN_FAILURE_JOB_NAMES = (
    # .github/actions/commit-snapshots, used by ci-backend.yml and ci-mcp.yml
    "Commit snapshot changes",
    # `vr run complete` exits 1 on detected visual changes; ci-storybook.yml and ci-e2e-playwright.yml
    "Complete Visual Review run",
)
# The repo those names were read out of. A job's display name is free text in a workflow file, so the
# carve-out applies only to the repo it was written for: another team's job that happens to share a
# name fails for its own reasons and has to stay eligible for the flaky-check signal. Every team with
# CI signals enabled runs this query over its own repos, so an unscoped name match would silently
# drop their finding.
BY_DESIGN_FAILURE_REPO = "PostHog/posthog"

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
    -- Written as an OR of negations rather than NOT(name AND owner AND repo) so that a row with an
    -- unresolved owner or name keeps its observation instead of being dropped by a NULL comparison.
       AND (j.name NOT IN {by_design_failure_job_names}
            OR lower(r.repo_owner) != {by_design_failure_repo_owner}
            OR lower(r.repo_name) != {by_design_failure_repo_name})
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
    by_design_repo_owner, by_design_repo_name = BY_DESIGN_FAILURE_REPO.casefold().split("/")
    response = curated.run(
        _SELECT.replace("__JOBS_SOURCE__", jobs_source).replace(
            "__RUNS_SOURCE__", curated.run_source(started_floor=True)
        ),
        query_type="engineering_analytics.workflow_flakiness",
        workload=workload,
        placeholders={
            "date_from": ast.Constant(value=date_from),
            "min_failed_duration_seconds": ast.Constant(value=min_failed_duration_seconds),
            "by_design_failure_job_names": ast.Constant(value=list(BY_DESIGN_FAILURE_JOB_NAMES)),
            "by_design_failure_repo_owner": ast.Constant(value=by_design_repo_owner),
            "by_design_failure_repo_name": ast.Constant(value=by_design_repo_name),
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
