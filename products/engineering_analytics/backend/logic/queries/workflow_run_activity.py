"""Curated query: compact per-run points for the run-activity chart.

Lists one workflow's runs over a window as the minimal shape the chart plots (start / duration /
conclusion / branch / attributed PR), newest first, at a higher cap than the run-detail table. Kept
separate from ``workflow_run_list`` so the chart can span the full window — enough runs for the
scatter, the in-flight band, and the focus-lens brush — while the detail table stays capped at its
smaller list size. Fetches ``_LIMIT + 1`` rows so an overflow is reported as ``truncated`` rather than
silently dropped.

The ``run_started_at >= date_from`` filter also excludes runs whose start timestamp didn't parse
(``NULL``), which is intended: a run with no start time can't be placed on the chart's time axis. That
is why ``WorkflowRunActivityPoint.run_started_at`` is non-null while the shared run-detail shape is not.
"""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import WorkflowRunActivity, WorkflowRunActivityPoint
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

# The chart plots a point per run and needs enough span to cover the window: an order of magnitude
# above the run-detail table's cap (workflow_run_list._LIMIT = 200) so the scatter and focus-lens
# brush still see multiple days on busy workflows where the smaller cap collapses to a sub-day slice.
# Revisit this alongside that table cap if it changes materially, so the chart keeps spanning the window.
_LIMIT = 2000

_SELECT = f"""
    SELECT
        id, conclusion, run_started_at, duration_seconds, head_branch, pr_number
    FROM __RUNS_SOURCE__ AS r
    WHERE repo_owner = {{repo_owner}} AND repo_name = {{repo_name}} AND workflow_name = {{workflow_name}}
        AND run_started_at >= {{date_from}} __DATE_TO__ __BRANCH__
    ORDER BY run_started_at DESC, run_attempt DESC
    LIMIT {_LIMIT + 1}
"""


def query_workflow_run_activity(
    *,
    curated: CuratedGitHubSource,
    repo_owner: str,
    repo_name: str,
    workflow_name: str,
    date_from: datetime,
    date_to: datetime | None,
    branch: str | None = None,
) -> WorkflowRunActivity:
    placeholders: dict[str, ast.Expr] = {
        "repo_owner": ast.Constant(value=repo_owner),
        "repo_name": ast.Constant(value=repo_name),
        "workflow_name": ast.Constant(value=workflow_name),
        "date_from": ast.Constant(value=date_from),
    }
    date_to_clause = ""
    if date_to is not None:
        date_to_clause = "AND run_started_at <= {date_to}"
        placeholders["date_to"] = ast.Constant(value=date_to)
    # An empty/whitespace branch is "no filter", not a literal match on '' — mirrors workflow_run_list.
    branch = branch.strip() if branch else None
    branch_clause = ""
    if branch:
        branch_clause = "AND head_branch = {branch}"
        placeholders["branch"] = ast.Constant(value=branch)
    response = curated.run(
        _SELECT.replace("__RUNS_SOURCE__", curated.run_source())
        .replace("__DATE_TO__", date_to_clause)
        .replace("__BRANCH__", branch_clause),
        query_type="engineering_analytics.workflow_run_activity",
        placeholders=placeholders,
    )
    rows = response.results or []
    truncated = len(rows) > _LIMIT
    points = [_to_point(row) for row in rows[:_LIMIT]]
    return WorkflowRunActivity(points=points, truncated=truncated, limit=_LIMIT)


def _to_point(row: tuple) -> WorkflowRunActivityPoint:
    run_id, conclusion, run_started_at, duration_seconds, head_branch, pr_number = row
    return WorkflowRunActivityPoint(
        run_id=int(run_id),
        # Empty string means "no conclusion yet" (still running) — normalize to None for the contract.
        conclusion=conclusion or None,
        run_started_at=run_started_at,
        duration_seconds=int(duration_seconds) if duration_seconds is not None else None,
        head_branch=head_branch or "",
        pr_number=int(pr_number) if pr_number is not None else 0,
    )
