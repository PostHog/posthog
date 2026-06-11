"""Curated query: per-workflow CI health over a window.

Run counts, success rate, and duration percentiles per ``workflow_name`` for runs
started within ``[date_from, date_to]`` (``date_to`` optional). Rates and
percentiles are over completed runs only, so they are ``None`` for a window with
no completed runs.
"""

import math
from datetime import date, datetime, timedelta

from posthog.hogql import ast

from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import RepoRef, WorkflowHealthDay, WorkflowHealthItem
from products.engineering_analytics.backend.logic.queries import _curated

_LIMIT = 100
# Generous bound: _LIMIT workflows x ~1 row per day for windows up to a quarter.
_DAILY_LIMIT = 10000

_SELECT = f"""
    SELECT
        repo_owner,
        repo_name,
        workflow_name,
        count() AS run_count,
        countIf(status = 'completed' AND conclusion = 'success') / nullIf(countIf(status = 'completed'), 0) AS success_rate,
        quantileIf(0.5)(duration_seconds, status = 'completed') AS p50_seconds,
        quantileIf(0.95)(duration_seconds, status = 'completed') AS p95_seconds,
        max(if(conclusion = 'failure', run_started_at, NULL)) AS last_failure_at
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {{date_from}} __DATE_TO__
    GROUP BY repo_owner, repo_name, workflow_name
    ORDER BY run_count DESC
    LIMIT {_LIMIT}
"""

_DAILY_SELECT = f"""
    SELECT
        repo_owner,
        repo_name,
        workflow_name,
        toDate(run_started_at) AS day,
        count() AS run_count,
        countIf(status = 'completed') AS completed,
        countIf(status = 'completed' AND conclusion = 'success') AS successes
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {{date_from}} __DATE_TO__
    GROUP BY repo_owner, repo_name, workflow_name, day
    LIMIT {_DAILY_LIMIT}
"""


def query_workflow_health(
    *,
    team: Team,
    date_from: datetime,
    date_to: datetime | None,
) -> list[WorkflowHealthItem]:
    date_to_clause = "AND run_started_at <= {date_to}" if date_to is not None else ""
    placeholders: dict[str, ast.Expr] = {"date_from": ast.Constant(value=date_from)}
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)

    sql = _SELECT.replace("__RUNS_SOURCE__", _curated.run_source()).replace("__DATE_TO__", date_to_clause)
    response = _curated.run_query(
        sql,
        team=team,
        query_type="engineering_analytics.workflow_health",
        placeholders=placeholders,
    )
    if not response.results:
        return []

    daily_sql = _DAILY_SELECT.replace("__RUNS_SOURCE__", _curated.run_source()).replace("__DATE_TO__", date_to_clause)
    daily_response = _curated.run_query(
        daily_sql,
        team=team,
        query_type="engineering_analytics.workflow_health_daily",
        placeholders=placeholders,
    )
    days_by_workflow: dict[tuple[str, str, str], dict[date, WorkflowHealthDay]] = {}
    for repo_owner, repo_name, workflow_name, day, run_count, completed, successes in daily_response.results or []:
        day = day.date() if isinstance(day, datetime) else day
        days_by_workflow.setdefault((repo_owner, repo_name, workflow_name), {})[day] = WorkflowHealthDay(
            day=day, run_count=run_count, completed=completed, successes=successes
        )

    window_days = _window_days(date_from, date_to)
    return [
        WorkflowHealthItem(
            repo=RepoRef(provider="github", owner=repo_owner, name=repo_name),
            workflow_name=workflow_name,
            run_count=run_count,
            success_rate=_to_opt_float(success_rate),
            p50_seconds=_to_opt_float(p50_seconds),
            p95_seconds=_to_opt_float(p95_seconds),
            last_failure_at=last_failure_at,
            daily=[
                days_by_workflow.get((repo_owner, repo_name, workflow_name), {}).get(
                    day, WorkflowHealthDay(day=day, run_count=0, completed=0, successes=0)
                )
                for day in window_days
            ],
        )
        for repo_owner, repo_name, workflow_name, run_count, success_rate, p50_seconds, p95_seconds, last_failure_at in response.results
    ]


def _window_days(date_from: datetime, date_to: datetime | None) -> list[date]:
    start = date_from.date()
    end = (date_to or datetime.now(tz=date_from.tzinfo)).date()
    if end < start:
        return []
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _to_opt_float(value: float | None) -> float | None:
    # quantileIf over an empty window returns NaN; nullIf division returns None.
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)
