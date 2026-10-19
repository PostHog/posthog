"""The default-branch runs that a CI timing comparison may sample.

A candidate is a completed run of the same workflow, on the same engine, that a push or a schedule
started on the repository's default branch. The newest ``RUNS_SCANNED`` are returned, because the
caller reads every job of every candidate.
"""

from datetime import datetime

from posthog.hogql import ast

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.facade.contracts import CIEngine, WorkflowRunDetail
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import run_started_floor_constant

RUNS_SCANNED = 40

# A pull request from a fork branch that has the default branch's name carries that name as its head
# branch, so the branch alone does not prove a default-branch run. The trigger event does. A run with
# no recorded event (a Depot CI run, or a table that lacks the column) qualifies only when no pull
# request is attributed to it.
_NOT_A_PULL_REQUEST_RUN = "if(ifNull(event, '') = '', pr_number = 0, NOT startsWith(event, 'pull_request'))"

# One row more than the scan reads, which tells the caller that more eligible runs existed.
_SELECT = f"""
    SELECT id, run_attempt, head_sha, run_started_at, native_run_id, native_workflow_run_id
    FROM __RUNS_SOURCE__ AS r
    WHERE repo_owner = {{repo_owner}} AND repo_name = {{repo_name}}
        AND ci_engine = {{ci_engine}}
        AND __WORKFLOW_IDENTITY__
        AND head_branch = {{default_branch}}
        AND {_NOT_A_PULL_REQUEST_RUN}
        AND NOT is_merge_queue
        AND status = 'completed'
        AND run_started_at >= {{date_from}}
        AND id != {{run_id}}
    ORDER BY run_started_at DESC, id DESC, run_attempt DESC
    LIMIT 1 BY id
    LIMIT {RUNS_SCANNED + 1}
"""


@frozen
class TimingCandidateRun:
    run_id: int
    run_attempt: int
    ci_engine: CIEngine
    head_sha: str
    run_started_at: datetime
    native_run_id: str | None
    native_workflow_run_id: str | None


@frozen
class TimingCandidates:
    # Newest first.
    runs: list[TimingCandidateRun]
    # True when more eligible runs existed in the window than ``runs`` holds.
    sampled: bool


def query_timing_candidates(
    *,
    curated: CuratedGitHubSource,
    run: WorkflowRunDetail,
    ci_engine: CIEngine,
    default_branch: str,
    window_start: datetime,
) -> TimingCandidates:
    """Runs comparable to ``run``. The workflow id identifies the workflow when ``run`` has one, because
    it survives a rename. The workflow name is the fallback."""
    placeholders: dict[str, ast.Expr] = {
        "repo_owner": ast.Constant(value=run.repo.owner),
        "repo_name": ast.Constant(value=run.repo.name),
        "ci_engine": ast.Constant(value=ci_engine.value),
        "default_branch": ast.Constant(value=default_branch),
        "date_from": ast.Constant(value=window_start),
        "run_started_floor": run_started_floor_constant(window_start),
        "run_id": ast.Constant(value=run.id),
    }
    if run.workflow_id is not None:
        identity = "workflow_id = {workflow_id}"
        placeholders["workflow_id"] = ast.Constant(value=run.workflow_id)
    else:
        identity = "workflow_name = {workflow_name}"
        placeholders["workflow_name"] = ast.Constant(value=run.workflow_name)
    response = curated.run(
        _SELECT.replace("__RUNS_SOURCE__", curated.run_source(started_floor=True)).replace(
            "__WORKFLOW_IDENTITY__", identity
        ),
        query_type="engineering_analytics.ci_timing_candidates",
        placeholders=placeholders,
    )
    rows = list(response.results or [])
    runs = [
        TimingCandidateRun(
            run_id=int(run_id),
            run_attempt=int(run_attempt) if run_attempt is not None else 1,
            ci_engine=ci_engine,
            head_sha=head_sha or "",
            run_started_at=run_started_at,
            native_run_id=native_run_id,
            native_workflow_run_id=native_workflow_run_id,
        )
        for run_id, run_attempt, head_sha, run_started_at, native_run_id, native_workflow_run_id in rows[:RUNS_SCANNED]
    ]
    return TimingCandidates(runs=runs, sampled=len(rows) > RUNS_SCANNED)
