"""Repository default branches carried by GitHub's repository payload."""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

_SELECT = """
    SELECT repo_owner, repo_name, argMax(default_branch, run_started_at) AS repo_default_branch
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {date_from} AND default_branch != ''
    GROUP BY repo_owner, repo_name
"""


def query_default_branches(*, curated: CuratedGitHubSource, date_from: datetime) -> dict[tuple[str, str], str]:
    response = curated.run(
        _SELECT.replace("__RUNS_SOURCE__", curated.run_source()),
        query_type="engineering_analytics.default_branches",
        placeholders={"date_from": ast.Constant(value=date_from)},
    )
    return {(owner, repo): branch for owner, repo, branch in response.results or [] if branch}
