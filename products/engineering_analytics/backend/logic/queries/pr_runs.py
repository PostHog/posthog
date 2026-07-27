"""HogQL assembly of all workflow runs attributed to a PR, across its commits.

Unlike ``pr_lifecycle`` (which scopes to the PR's current head SHA), this returns every run attributed
to the PR — so the detail page can show CI across all of the PR's pushes, grouped by commit. Newest run
first. Run-level only.

Attribution is the curated ``pr_number``, i.e. the FIRST PR in a run's ``pull_requests`` association
(see ``views/workflow_runs.py``). A run that lists this PR only in a later slot — uncommon: one head
commit tied to several open PRs — is credited to its first PR instead and won't appear here. That's the
same deliberate v1 simplification the rollup uses; it's a friction signal, not billing.
"""

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import WorkflowRunDetail
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._run_detail import RUN_DETAIL_COLUMNS, to_run_detail

# Safety bound: a very churny PR still can't return an unbounded set.
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
        _SELECT.replace("__RUNS_SOURCE__", curated.run_source()),
        query_type="engineering_analytics.pr_runs",
        placeholders={
            "pr_number": ast.Constant(value=pr_number),
            "repo_owner": ast.Constant(value=repo_owner),
            "repo_name": ast.Constant(value=repo_name),
        },
    )
    return [to_run_detail(row) for row in (response.results or [])]
