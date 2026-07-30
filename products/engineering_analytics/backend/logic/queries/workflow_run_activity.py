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

No-op gate runs (benign conclusion, settled in seconds — see ``NO_OP_RUN_FLAG``) are hidden here, not
client-side: on a workflow where most runs are no-ops the newest ``_LIMIT`` rows could be pure gate
runs, and a post-cap filter would leave the chart empty even though real executions exist in the
window. The query sorts real runs ahead of no-ops so the cap fills with real executions first, and the
no-ops are then dropped in Python — unless fewer than ``_MIN_REAL_RUNS`` real runs remain, in which
case everything is kept: duration alone can't tell a gate no-op from an intentionally fast workflow
(a lightweight guard check), so an all-fast workflow keeps its history instead of an empty chart. The
run-detail table always shows every run — only the chart hides no-ops.
"""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import WorkflowRunActivity, WorkflowRunActivityPoint
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    NO_OP_RUN_FLAG,
    branch_filter_clause,
    date_to_filter_clause,
)

# The chart plots a point per run and needs enough span to cover the window: an order of magnitude
# above the run-detail table's cap (workflow_run_list._LIMIT = 200) so the scatter and focus-lens
# brush still see multiple days on busy workflows where the smaller cap collapses to a sub-day slice.
# Revisit this alongside that table cap if it changes materially, so the chart keeps spanning the window.
_LIMIT = 2000

# Matches the chart's MIN_POINTS: below two real dots the scatter draws nothing anyway, so hiding
# the no-ops would blank a chart that still has runs to show.
_MIN_REAL_RUNS = 2

_SELECT = f"""
    SELECT
        id, conclusion, run_started_at, duration_seconds, head_branch, pr_number, head_sha,
        {NO_OP_RUN_FLAG} AS is_noop
    FROM __RUNS_SOURCE__ AS r
    WHERE repo_owner = {{repo_owner}} AND repo_name = {{repo_name}} AND workflow_name = {{workflow_name}}
        AND run_started_at >= {{date_from}} __DATE_TO__ __BRANCH__
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
        _SELECT.replace("__RUNS_SOURCE__", curated.run_source())
        .replace("__DATE_TO__", date_to_clause)
        .replace("__BRANCH__", branch_clause),
        query_type="engineering_analytics.workflow_run_activity",
        placeholders=placeholders,
    )
    rows = response.results or []
    truncated = len(rows) > _LIMIT
    capped = rows[:_LIMIT]
    real = [row for row in capped if not row[7]]
    # The threshold counts duration-bearing rows only: in-flight runs are kept but can't land on the
    # scatter, so real rows without durations must not veto the fallback — dropping the no-ops around
    # a lone completed run plus an in-flight one would leave the chart below MIN_POINTS and blank.
    plottable_real = sum(1 for row in real if row[3] is not None)
    chosen = real if plottable_real >= _MIN_REAL_RUNS else capped
    # The is_noop sort put real runs first — restore the newest-first order the chart contract promises.
    chosen = sorted(chosen, key=lambda row: row[2], reverse=True)
    points = [_to_point(row) for row in chosen]
    return WorkflowRunActivity(points=points, truncated=truncated, limit=_LIMIT)


def _to_point(row: tuple) -> WorkflowRunActivityPoint:
    run_id, conclusion, run_started_at, duration_seconds, head_branch, pr_number, head_sha, _is_noop = row
    return WorkflowRunActivityPoint(
        run_id=int(run_id),
        # Empty string means "no conclusion yet" (still running) — normalize to None for the contract.
        conclusion=conclusion or None,
        run_started_at=run_started_at,
        duration_seconds=int(duration_seconds) if duration_seconds is not None else None,
        head_branch=head_branch or "",
        pr_number=int(pr_number) if pr_number is not None else 0,
        head_sha=head_sha or "",
    )
