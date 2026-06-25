"""HogQL assembly of a single workflow's recent runs, for the workflow detail (runs list) page.

Embeds the curated ``github_workflow_runs`` builder as a subquery (via ``_curated``) and lists runs of
one ``workflow_name`` within a repo, newest first. Run-level only — per-job/step data isn't in the
warehouse yet. Re-runs share a run id; each attempt is its own row here (the detail page collapses to
the latest attempt), so the list mirrors what GitHub Actions shows.
"""

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import WorkflowRunDetail
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._run_detail import RUN_DETAIL_COLUMNS, to_run_detail

# Safety bound on the runs list (mirrors the PR table's cap philosophy).
_LIMIT = 200

_SELECT = f"""
    SELECT
        {RUN_DETAIL_COLUMNS}
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
    return [to_run_detail(row) for row in (response.results or [])]
