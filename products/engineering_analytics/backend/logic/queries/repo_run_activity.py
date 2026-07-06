"""Curated query: one collapsed point per default-branch commit for the repo-health chart.

The repo hub's master-health chart plots the health of the default branch over the window. A single
push to the default branch fans out into many workflow runs (one row per workflow file), so plotting
every ``github_workflow_runs`` row would show a cloud of dots per commit. Instead this collapses all of
a commit's workflow runs into **one point per ``head_sha``** — the unit an engineer reads as "did master
go green for this commit, and how long did its CI take":

- ``run_started_at`` = the earliest workflow start for the commit (when the commit's CI kicked off).
- ``duration_seconds`` = wall-clock from the first workflow start to the last workflow finish, and only
  once **every** workflow settled — while any is still running the commit's CI isn't done, so duration is
  null (the point drops off the scatter and feeds the in-flight band instead), mirroring the per-run chart.
- ``conclusion`` = the commit's overall verdict: red if **any** workflow decisively failed
  (``failure`` / ``timed_out``), else '' (still in flight) if any hasn't settled, else ``success`` when at
  least one passed, else ``neutral`` (only cancelled/skipped). One decisive failure turns the commit red,
  matching how a human reads a broken default branch.

Rows are first collapsed to the **latest run per ``(head_sha, workflow_name)``** (the same ``argMax``
rule as ``ci_rollup``), so a workflow that failed and was re-run to green reads green, and superseded
attempts don't stretch the commit's wall clock or flip its verdict.

Reuses the ``WorkflowRunActivity`` contract so the same ``RunActivityChart`` renders it. Same
``run_started_at >= date_from`` filter as ``workflow_run_activity`` (a commit whose earliest run has no
parseable start can't be placed on the time axis). Fetches ``_LIMIT + 1`` rows so an overflow reports as
``truncated`` rather than silently dropping the oldest commits.
"""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import WorkflowRunActivity, WorkflowRunActivityPoint
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

# One point per commit, so the cap is in commits (not runs) — comfortably above the busiest window's
# default-branch commit count while bounding the wire size. Newest commits win when the cap is hit.
_LIMIT = 2000

_SELECT = f"""
    SELECT
        max(w.id) AS run_id,
        multiIf(
            countIf(w.status = 'completed' AND w.conclusion IN ('failure', 'timed_out')) > 0, 'failure',
            countIf(w.status != 'completed') > 0, '',
            countIf(w.conclusion = 'success') > 0, 'success',
            'neutral'
        ) AS conclusion,
        min(w.run_started_at) AS run_started_at,
        if(countIf(w.status != 'completed') = 0, dateDiff('second', min(w.run_started_at), max(w.updated_at)), NULL)
            AS duration_seconds,
        any(w.head_branch) AS head_branch
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
        _SELECT.replace("__RUNS_SOURCE__", curated.run_source()).replace("__DATE_TO__", date_to_clause),
        query_type="engineering_analytics.repo_run_activity",
        placeholders=placeholders,
    )
    rows = response.results or []
    truncated = len(rows) > _LIMIT
    points = [_to_point(row) for row in rows[:_LIMIT]]
    return WorkflowRunActivity(points=points, truncated=truncated, limit=_LIMIT)


def _to_point(row: tuple) -> WorkflowRunActivityPoint:
    run_id, conclusion, run_started_at, duration_seconds, head_branch = row
    return WorkflowRunActivityPoint(
        run_id=int(run_id),
        # '' is the in-flight sentinel from the multiIf (not every workflow settled) — normalize to None.
        conclusion=conclusion or None,
        run_started_at=run_started_at,
        duration_seconds=int(duration_seconds) if duration_seconds is not None else None,
        head_branch=head_branch or "",
        # Default-branch commits aren't attributed to a single PR — the chart hides the PR line at 0.
        pr_number=0,
    )
