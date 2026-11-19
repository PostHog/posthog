"""Every workflow run attributed to a PR across all its pushes, newest first.

A run that lists this PR only in a later slot of its ``pull_requests`` association is credited to
the first PR of this repo in that association, so it does not appear here.
"""

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import WorkflowRunDetail
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._run_detail import RUN_DETAIL_COLUMNS, to_run_detail

_LIMIT = 500

_SELECT = f"""
    SELECT
        {RUN_DETAIL_COLUMNS}
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
        _SELECT.replace("__RUNS_SOURCE__", curated.run_source(live=True)),
        query_type="engineering_analytics.pr_runs",
        placeholders={
            "pr_number": ast.Constant(value=pr_number),
            "repo_owner": ast.Constant(value=repo_owner),
            "repo_name": ast.Constant(value=repo_name),
        },
    )
    return [to_run_detail(row) for row in (response.results or [])]
