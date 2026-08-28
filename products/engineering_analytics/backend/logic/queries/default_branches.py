"""Repository default branches, read from the PR snapshot's ``base.repo`` object.

The workflow_run webhook's ``repository`` is GitHub's minimal repository representation and
carries no ``default_branch`` field, so the runs table can never answer this (every landed row
is empty). A PR's ``base.repo`` is a full repository object and does carry it; taking the
``argMax`` over ``updated_at`` means a repo that renames its default branch converges as soon
as any of its PRs updates. A repo with no PR rows yet resolves nothing, and
broken-default-branch detection skips it rather than guessing.
"""

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

# Generous, deterministic bound so a team with many synced repos can't hit HogQL's default 100-row
# cap and silently drop default-branch detection for the overflow (see pr_cost.py's convention).
_LIMIT = 10000

# Unwindowed on purpose: a window on updated_at would blank the map for a repo with no recent
# PR activity, disabling broken-default-branch detection exactly when the repo is quiet. The
# full snapshot scan (one row per PR) rides the hourly OFFLINE sweep, not a request path.
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
