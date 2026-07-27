"""Shared mapping of the curated workflow-run columns into ``WorkflowRunDetail``.

``pr_runs`` / ``workflow_run`` / ``workflow_run_list`` all select the same run columns and build the
same contract. Centralizing the column list and the row mapper keeps a future field add from being
applied to two of the three call sites and silently mis-mapping a column.
"""

from typing import Any

from products.engineering_analytics.backend.facade.contracts import RepoRef, WorkflowRunDetail

# The run columns every run-detail query selects, in order — kept in lockstep with the unpacking below.
RUN_DETAIL_COLUMNS = """
        id, workflow_name, head_sha, head_branch, status, conclusion,
        run_started_at, updated_at, duration_seconds, run_attempt, pr_number,
        repo_owner, repo_name
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
        repo_owner,
        repo_name,
    ) = row
    return WorkflowRunDetail(
        repo=RepoRef(provider="github", owner=repo_owner, name=repo_name),
        id=int(run_id),
        workflow_name=workflow_name,
        head_sha=head_sha or "",
        head_branch=head_branch or "",
        status=status or "",
        # Empty string means "no conclusion yet" (running) — normalize to None for the contract.
        conclusion=conclusion or None,
        # Null for a queued/barely-started run whose timestamp the curated builder couldn't parse.
        run_started_at=run_started_at,
        updated_at=updated_at,
        duration_seconds=int(duration_seconds) if duration_seconds is not None else None,
        run_attempt=int(run_attempt) if run_attempt is not None else 1,
        pr_number=int(pr_number) if pr_number is not None else 0,
    )
