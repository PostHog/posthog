"""Maps the curated workflow-run columns into ``WorkflowRunDetail`` for every run-detail query."""

from typing import Any

from products.engineering_analytics.backend.facade.contracts import CIEngine, RepoRef, WorkflowRunDetail

# to_run_detail unpacks rows by position, so keep this column order in sync with it.
RUN_DETAIL_COLUMNS = """
        id, workflow_name, head_sha, head_branch, status, conclusion,
        run_started_at, updated_at, duration_seconds, run_attempt, pr_number, commit_pr_number,
        repo_owner, repo_name, is_merge_queue, ci_engine, native_run_id, native_workflow_run_id,
        workflow_id, event
"""


def to_run_detail(row: tuple[Any, ...]) -> WorkflowRunDetail:
    (
        run_id,
        workflow_name,
        head_sha,
        head_branch,
        status,
        conclusion,
        run_started_at,
        updated_at,
        duration_seconds,
        run_attempt,
        pr_number,
        commit_pr_number,
        repo_owner,
        repo_name,
        is_merge_queue,
        ci_engine,
        native_run_id,
        native_workflow_run_id,
        workflow_id,
        event,
    ) = row
    return WorkflowRunDetail(
        repo=RepoRef(provider="github", owner=repo_owner, name=repo_name),
        id=int(run_id),
        workflow_name=workflow_name,
        head_sha=head_sha or "",
        head_branch=head_branch or "",
        status=status or "",
        # A running run has an empty conclusion.
        conclusion=conclusion or None,
        run_started_at=run_started_at,
        updated_at=updated_at,
        duration_seconds=int(duration_seconds) if duration_seconds is not None else None,
        run_attempt=int(run_attempt) if run_attempt is not None else 1,
        pr_number=int(pr_number) if pr_number is not None else 0,
        commit_pr_number=int(commit_pr_number) if commit_pr_number is not None else None,
        is_merge_queue=bool(is_merge_queue),
        ci_engine=CIEngine(ci_engine),
        native_run_id=native_run_id,
        native_workflow_run_id=native_workflow_run_id,
        workflow_id=int(workflow_id) if workflow_id is not None else None,
        event=event or None,
    )
