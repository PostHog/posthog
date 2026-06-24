"""HogQL assembly of all workflow runs attributed to a PR, across its commits.

Unlike ``pr_lifecycle`` (which scopes to the PR's current head SHA), this returns every run linked to
the PR via the ``pull_requests`` association — so the detail page can show CI across all of the PR's
pushes, grouped by commit. Newest run first. Run-level only.
"""

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import RepoRef, WorkflowRunDetail
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

# Safety bound: a very churny PR still can't return an unbounded set.
_LIMIT = 500

_SELECT = f"""
    SELECT
        id, workflow_name, head_sha, head_branch, status, conclusion,
        run_started_at, updated_at, duration_seconds, run_attempt, pr_number,
        repo_owner, repo_name
    FROM __RUNS_SOURCE__ AS r
    WHERE pr_number = {{pr_number}} AND repo_owner = {{repo_owner}} AND repo_name = {{repo_name}}
    ORDER BY run_started_at DESC, run_attempt DESC
    LIMIT {_LIMIT}
"""


def query_pr_runs(
    *,
    curated: CuratedGitHubSource,
    pr_number: int,
    repo_owner: str,
    repo_name: str,
) -> list[WorkflowRunDetail]:
    response = curated.run(
        _SELECT.replace("__RUNS_SOURCE__", curated.run_source()),
        query_type="engineering_analytics.pr_runs",
        placeholders={
            "pr_number": ast.Constant(value=pr_number),
            "repo_owner": ast.Constant(value=repo_owner),
            "repo_name": ast.Constant(value=repo_name),
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
            pr_number=int(pr_number_value) if pr_number_value is not None else 0,
        )
        for (
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
            pr_number_value,
            _repo_owner,
            _repo_name,
        ) in response.results
    ]
