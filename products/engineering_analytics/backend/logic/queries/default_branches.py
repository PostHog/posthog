"""Repository default branches, read from the PR snapshot's ``base.repo`` object.

The workflow_run webhook's ``repository`` carries no ``default_branch`` field, so the runs table
cannot answer this. A repo with no PR rows resolves nothing.
"""

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

# An explicit bound, because HogQL caps a query that names no LIMIT at 100 rows.
_LIMIT = 10000

# A window on updated_at would drop a repo with no recent PR activity.
_SELECT = f"""
    SELECT repo_owner, repo_name, argMax(default_branch, updated_at) AS repo_default_branch
    FROM __PR_SOURCE__ AS pr
    WHERE default_branch != ''
    GROUP BY repo_owner, repo_name
    ORDER BY repo_owner, repo_name
    LIMIT {_LIMIT}
"""


def query_default_branches(
    *, curated: CuratedGitHubSource, workload: Workload = Workload.DEFAULT
) -> dict[tuple[str, str], str]:
    response = curated.run(
        _SELECT.replace("__PR_SOURCE__", curated.pr_source()),
        query_type="engineering_analytics.default_branches",
        workload=workload,
    )
    return {(owner, repo): branch for owner, repo, branch in response.results or [] if branch}
