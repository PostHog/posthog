"""One point per commit of a branch, collapsed from the latest run of each of the commit's workflows.

A commit fails when any workflow decisively failed, and has no conclusion or duration until every
workflow settles. A workflow that a re-run turned green counts as green.
"""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import WorkflowRunActivity, WorkflowRunActivityPoint
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import DECISIVE_FAILURE_CONCLUSIONS_SQL

# The cap counts commits, not runs. The newest commits are kept when it is hit.
_LIMIT = 2000

_SELECT = f"""
    SELECT
        max(w.id) AS run_id,
        multiIf(
            countIf(w.status = 'completed' AND w.conclusion IN ({DECISIVE_FAILURE_CONCLUSIONS_SQL})) > 0, 'failure',
            countIf(w.status != 'completed') > 0, '',
            countIf(w.conclusion = 'success') > 0, 'success',
            'neutral'
        ) AS conclusion,
        min(w.run_started_at) AS run_started_at,
        if(countIf(w.status != 'completed') = 0, dateDiff('second', min(w.run_started_at), max(w.updated_at)), NULL)
            AS duration_seconds,
        any(w.head_branch) AS head_branch,
        w.head_sha AS head_sha
    FROM (
        SELECT
            argMax(r.id, r.run_started_at) AS id,
            argMax(r.status, r.run_started_at) AS status,
            argMax(r.conclusion, r.run_started_at) AS conclusion,
            max(r.run_started_at) AS run_started_at,
            argMax(r.updated_at, r.run_started_at) AS updated_at,
            any(r.head_branch) AS head_branch,
            r.head_sha AS head_sha
        FROM __RUNS_SOURCE__ AS r
        WHERE r.run_started_at >= {{date_from}} AND r.head_branch = {{branch}} __DATE_TO__
        GROUP BY r.head_sha, r.workflow_name
    ) AS w
    GROUP BY w.head_sha
    ORDER BY min(w.run_started_at) DESC
    LIMIT {_LIMIT + 1}
"""


def query_repo_run_activity(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    branch: str,
) -> WorkflowRunActivity:
    date_to_clause = ""
    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=date_from),
        "branch": ast.Constant(value=branch),
    }
    if date_to is not None:
        date_to_clause = "AND r.run_started_at <= {date_to}"
        placeholders["date_to"] = ast.Constant(value=date_to)
    response = curated.run(
        _SELECT.replace("__RUNS_SOURCE__", curated.run_source(since=date_from)).replace("__DATE_TO__", date_to_clause),
        query_type="engineering_analytics.repo_run_activity",
        placeholders=placeholders,
    )
    rows = response.results or []
    truncated = len(rows) > _LIMIT
    points = [_to_point(row) for row in rows[:_LIMIT]]
    return WorkflowRunActivity(points=points, truncated=truncated, limit=_LIMIT)


def _to_point(row: tuple) -> WorkflowRunActivityPoint:
    run_id, conclusion, run_started_at, duration_seconds, head_branch, head_sha = row
    return WorkflowRunActivityPoint(
        run_id=int(run_id),
        # The query returns '' while any workflow of the commit is unsettled.
        conclusion=conclusion or None,
        run_started_at=run_started_at,
        duration_seconds=int(duration_seconds) if duration_seconds is not None else None,
        head_branch=head_branch or "",
        # A commit point carries no PR attribution, and the chart hides the PR line at 0.
        pr_number=0,
        head_sha=head_sha or "",
    )
