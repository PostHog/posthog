"""HogQL against ``github_workflow_runs`` for the workflow_report tool.

All columns used here are top-level scalars on the warehouse table, so there is
no nested-JSON access. Duration is derived as ``updated_at - run_started_at``;
``conclusion`` is a nullable string ('success', 'failure', ... or null while a
run is in progress).
"""

from datetime import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team

from ...facade.contracts import WorkflowReportRow

DEFAULT_WORKFLOW_LIMIT = 10


def query_workflow_report(
    *,
    team: Team,
    date_from: datetime,
    date_to: datetime,
    limit: int = DEFAULT_WORKFLOW_LIMIT,
) -> list[WorkflowReportRow]:
    query = parse_select(
        """
        SELECT
            name AS workflow_name,
            count() AS total_runs,
            countIf(conclusion = 'success') / count() AS success_rate,
            quantile(0.5)(dateDiff('second', run_started_at, updated_at)) AS median_duration_seconds,
            quantile(0.95)(dateDiff('second', run_started_at, updated_at)) AS p95_duration_seconds,
            if(
                countIf(conclusion = 'failure') > 0,
                maxIf(updated_at, conclusion = 'failure'),
                NULL
            ) AS last_failed_at
        FROM github_workflow_runs
        WHERE created_at >= {date_from} AND created_at < {date_to}
        GROUP BY name
        ORDER BY median_duration_seconds DESC
        LIMIT {limit}
        """,
        placeholders={
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
            "limit": ast.Constant(value=limit),
        },
    )
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="engineering_analytics.workflow_report",
    )
    return [_to_row(row) for row in response.results]


def _to_row(row: tuple) -> WorkflowReportRow:
    workflow_name, total_runs, success_rate, median_duration, p95_duration, last_failed_at = row
    return WorkflowReportRow(
        workflow_name=workflow_name,
        total_runs=total_runs,
        success_rate=success_rate,
        median_duration_seconds=median_duration,
        p95_duration_seconds=p95_duration,
        last_failed_at=last_failed_at,
    )
