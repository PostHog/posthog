"""HogQL assembly of a single workflow's recent runs, for the workflow detail (runs list) page.

Embeds the curated ``github_workflow_runs`` builder as a subquery (via ``_curated``) and lists runs of
one ``workflow_name`` within a repo, newest first. Run-level only — per-job/step data isn't in the
warehouse yet. Re-runs share a run id; each attempt is its own row here (the detail page collapses to
the latest attempt), so the list mirrors what GitHub Actions shows.
"""

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import RepoRef, WorkflowRunDetail
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

# Safety bound on the runs list (mirrors the PR table's cap philosophy).
_LIMIT = 200

_SELECT = f"""
    SELECT
        id, workflow_name, head_sha, head_branch, status, conclusion,
        run_started_at, updated_at, duration_seconds, run_attempt, pr_number,
        repo_owner, repo_name
    FROM __RUNS_SOURCE__ AS r
    WHERE repo_owner = {{repo_owner}} AND repo_name = {{repo_name}} AND workflow_name = {{workflow_name}}
    ORDER BY run_started_at DESC, run_attempt DESC
    LIMIT {_LIMIT}
"""


def query_workflow_run_list(
    *,
    curated: CuratedGitHubSource,
    repo_owner: str,
    repo_name: str,
    workflow_name: str,
) -> list[WorkflowRunDetail]:
    response = curated.run(
        _SELECT.replace("__RUNS_SOURCE__", curated.run_source()),
        query_type="engineering_analytics.workflow_run_list",
        placeholders={
            "repo_owner": ast.Constant(value=repo_owner),
            "repo_name": ast.Constant(value=repo_name),
            "workflow_name": ast.Constant(value=workflow_name),
        },
    )
    return [
        WorkflowRunDetail(
            repo=RepoRef(provider="github", owner=repo_owner, name=repo_name),
            id=int(run_id),
            workflow_name=workflow_name,
            head_sha=head_sha or "",
            head_branch=head_branch or "",
            status=status or "",
            conclusion=conclusion or None,
            run_started_at=run_started_at,
            updated_at=updated_at,
            duration_seconds=int(duration_seconds) if duration_seconds is not None else None,
            run_attempt=int(run_attempt) if run_attempt is not None else 1,
            pr_number=int(pr_number) if pr_number is not None else 0,
        )
        for (
            run_id,
            _workflow_name,
            head_sha,
            head_branch,
            status,
            conclusion,
            run_started_at,
            updated_at,
            duration_seconds,
            run_attempt,
            pr_number,
            _repo_owner,
            _repo_name,
        ) in response.results
    ]
