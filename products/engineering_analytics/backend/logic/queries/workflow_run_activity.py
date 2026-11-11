"""One workflow's runs in a window as points for the run-activity chart, newest first.

No-op gate runs (``NO_OP_RUN_FLAG``) are hidden unless fewer than ``_MIN_REAL_RUNS`` other runs have
a duration. Every point has a start time, because a run with none cannot be placed on the time axis.
"""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import (
    CIEngine,
    WorkflowHealthRunScope,
    WorkflowRunActivity,
    WorkflowRunActivityPoint,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    NO_OP_RUN_FLAG,
    branch_filter_clause,
    date_to_filter_clause,
    run_scope_filter_clause,
)

# Sized well above workflow_run_list._LIMIT, so the chart spans several days of a busy workflow.
_LIMIT = 2000

# Kept in sync with MIN_POINTS in RunActivityChart.tsx. The chart draws nothing below that many
# points, so hiding the no-ops there would blank a chart that still has runs to show.
_MIN_REAL_RUNS = 2

# The sort puts no-op runs last, so the cap fills with real runs first. A filter applied after a
# newest-first cap could leave the chart empty on a workflow where most runs are no-ops.

_SELECT = f"""
    SELECT
        id, conclusion, run_started_at, duration_seconds, head_branch, pr_number, head_sha,
        {NO_OP_RUN_FLAG} AS is_noop, ci_engine
    FROM __RUNS_SOURCE__ AS r
    WHERE repo_owner = {{repo_owner}} AND repo_name = {{repo_name}} AND workflow_name = {{workflow_name}}
        AND run_started_at >= {{date_from}} __DATE_TO__ __BRANCH__ __RUN_SCOPE__
    ORDER BY is_noop ASC, run_started_at DESC, run_attempt DESC
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
    run_scope: WorkflowHealthRunScope = WorkflowHealthRunScope.ALL,
) -> WorkflowRunActivity:
    placeholders: dict[str, ast.Expr] = {
        "repo_owner": ast.Constant(value=repo_owner),
        "repo_name": ast.Constant(value=repo_name),
        "workflow_name": ast.Constant(value=workflow_name),
        "date_from": ast.Constant(value=date_from),
    }
    date_to_clause = date_to_filter_clause(date_to, placeholders)
    branch_clause = branch_filter_clause(branch, placeholders)
    response = curated.run(
        _SELECT.replace("__RUNS_SOURCE__", curated.run_source(since=date_from))
        .replace("__DATE_TO__", date_to_clause)
        .replace("__BRANCH__", branch_clause)
        .replace("__RUN_SCOPE__", run_scope_filter_clause(run_scope)),
        query_type="engineering_analytics.workflow_run_activity",
        placeholders=placeholders,
    )
    rows = response.results or []
    truncated = len(rows) > _LIMIT
    capped = rows[:_LIMIT]
    real = [row for row in capped if not row[7]]
    # Only rows with a duration count, because a run in progress cannot be plotted. Duration alone
    # cannot tell a gate no-op from a fast workflow, so a workflow with too few other runs keeps all.
    plottable_real = sum(1 for row in real if row[3] is not None)
    chosen = real if plottable_real >= _MIN_REAL_RUNS else capped
    # The query sorted on is_noop first, so this restores the newest-first order callers expect.
    chosen = sorted(chosen, key=lambda row: row[2], reverse=True)
    points = [_to_point(row) for row in chosen]
    return WorkflowRunActivity(points=points, truncated=truncated, limit=_LIMIT)


def _to_point(row: tuple) -> WorkflowRunActivityPoint:
    run_id, conclusion, run_started_at, duration_seconds, head_branch, pr_number, head_sha, _is_noop, ci_engine = row
    return WorkflowRunActivityPoint(
        run_id=int(run_id),
        conclusion=conclusion or None,
        run_started_at=run_started_at,
        duration_seconds=int(duration_seconds) if duration_seconds is not None else None,
        head_branch=head_branch or "",
        pr_number=int(pr_number) if pr_number is not None else 0,
        head_sha=head_sha or "",
        ci_engine=CIEngine(ci_engine),
    )
