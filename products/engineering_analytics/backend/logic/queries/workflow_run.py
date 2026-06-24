"""HogQL assembly of a single workflow run, for the run detail page.

Embeds the curated ``github_workflow_runs`` builder as a subquery (via ``_curated``) and selects one
run by its GitHub Actions ``id``. Run-level only — per-job/step data isn't in the warehouse yet. A run
can have multiple attempts (re-runs) sharing the same id; the latest attempt is the canonical row.
"""

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import RepoRef, WorkflowRunDetail
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

_SELECT = """
    SELECT
        id, workflow_name, head_sha, head_branch, status, conclusion,
        run_started_at, updated_at, duration_seconds, run_attempt, pr_number,
        repo_owner, repo_name
    FROM __RUNS_SOURCE__ AS r
    WHERE id = {run_id}
    ORDER BY run_attempt DESC
    LIMIT 1
"""


def query_workflow_run(*, curated: CuratedGitHubSource, run_id: int) -> WorkflowRunDetail | None:
    response = curated.run(
        _SELECT.replace("__RUNS_SOURCE__", curated.run_source()),
        query_type="engineering_analytics.workflow_run",
        placeholders={"run_id": ast.Constant(value=run_id)},
    )
    if not response.results:
        return None

    (
        run_id_value,
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
    ) = response.results[0]

    return WorkflowRunDetail(
        repo=RepoRef(provider="github", owner=repo_owner, name=repo_name),
        id=int(run_id_value),
        workflow_name=workflow_name,
        head_sha=head_sha or "",
        head_branch=head_branch or "",
        status=status or "",
        # Empty string means "no conclusion yet" (running) — normalize to None for the contract.
        conclusion=conclusion or None,
        run_started_at=run_started_at,
        updated_at=updated_at,
        duration_seconds=int(duration_seconds) if duration_seconds is not None else None,
        run_attempt=int(run_attempt) if run_attempt is not None else 1,
        pr_number=int(pr_number) if pr_number is not None else 0,
    )
