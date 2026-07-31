"""Repository default branches carried by GitHub's repository payload."""

from datetime import datetime

from posthog.hogql import ast

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import run_started_floor_constant

# Generous, deterministic bound so a team with many synced repos can't hit HogQL's default 100-row
# cap and silently drop default-branch detection for the overflow (see pr_cost.py's convention).
_LIMIT = 10000

_SELECT = f"""
    SELECT repo_owner, repo_name, argMax(default_branch, run_started_at) AS repo_default_branch
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {{date_from}} AND default_branch != ''
    GROUP BY repo_owner, repo_name
    ORDER BY repo_owner, repo_name
    LIMIT {_LIMIT}
"""


def query_default_branches(
    *, curated: CuratedGitHubSource, date_from: datetime, workload: Workload = Workload.DEFAULT
) -> dict[tuple[str, str], str]:
    response = curated.run(
        # started_floor lets the scan prune on the raw-string floor; the parsed run_started_at
        # filter alone can't push down, so without it this full-scans the runs table each sweep.
        _SELECT.replace("__RUNS_SOURCE__", curated.run_source(started_floor=True)),
        query_type="engineering_analytics.default_branches",
        placeholders={
            "date_from": ast.Constant(value=date_from),
            "run_started_floor": run_started_floor_constant(date_from),
        },
        workload=workload,
    )
    return {(owner, repo): branch for owner, repo, branch in response.results or [] if branch}
