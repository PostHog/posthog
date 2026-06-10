"""Curated query: per-workflow CI health over a window.

Run counts, success rate, and duration percentiles per ``workflow_name`` for runs
started within ``[date_from, date_to]`` (``date_to`` optional). Rates and
percentiles are over completed runs only, so they are ``None`` for a window with
no completed runs.
"""

import math
from datetime import datetime

from posthog.hogql import ast

from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import WorkflowHealthItem
from products.engineering_analytics.backend.logic.queries import _curated

_LIMIT = 100

_SELECT = f"""
    SELECT
        workflow_name,
        count() AS run_count,
        countIf(status = 'completed' AND conclusion = 'success') / nullIf(countIf(status = 'completed'), 0) AS success_rate,
        quantileIf(0.5)(duration_seconds, status = 'completed') AS p50_seconds,
        quantileIf(0.95)(duration_seconds, status = 'completed') AS p95_seconds,
        max(if(conclusion = 'failure', run_started_at, NULL)) AS last_failure_at
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {{date_from}} __DATE_TO__
    GROUP BY workflow_name
    ORDER BY run_count DESC
    LIMIT {_LIMIT}
"""


def query_workflow_health(
    *,
    team: Team,
    date_from: datetime,
    date_to: datetime | None,
) -> list[WorkflowHealthItem]:
    date_to_clause = "AND run_started_at <= {date_to}" if date_to is not None else ""
    sql = _SELECT.replace("__RUNS_SOURCE__", _curated.run_source()).replace("__DATE_TO__", date_to_clause)

    placeholders: dict[str, ast.Expr] = {"date_from": ast.Constant(value=date_from)}
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)

    response = _curated.run_query(
        sql,
        team=team,
        query_type="engineering_analytics.workflow_health",
        placeholders=placeholders,
    )
    return [
        WorkflowHealthItem(
            workflow_name=workflow_name,
            run_count=run_count,
            success_rate=_to_opt_float(success_rate),
            p50_seconds=_to_opt_float(p50_seconds),
            p95_seconds=_to_opt_float(p95_seconds),
            last_failure_at=last_failure_at,
        )
        for workflow_name, run_count, success_rate, p50_seconds, p95_seconds, last_failure_at in response.results
    ]


def _to_opt_float(value: float | None) -> float | None:
    # quantileIf over an empty window returns NaN; nullIf division returns None.
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)
