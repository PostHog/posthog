"""Curated query: per-workflow CI health over a window.

Run counts, success rate, and duration percentiles per ``workflow_name`` for runs
started within ``[date_from, date_to]`` (``date_to`` optional), optionally scoped to
a single ``head_branch`` and/or attributed pull-request runs. Rates are over completed
runs. Percentiles are over completed runs by default, or successful runs when requested,
so they are ``None`` for a window with no matching runs.

The per-bucket history adapts its granularity to the window length (hour / day / week)
so the trend sparkline keeps a readable number of points — per-day buckets are useless
for a 24h window and far too many for a year.
"""

import math
from datetime import date, datetime, timedelta
from typing import Literal

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import (
    RepoRef,
    WorkflowHealthBucket,
    WorkflowHealthDurationFilter,
    WorkflowHealthItem,
    WorkflowHealthRunScope,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    branch_filter_clause,
    run_scope_filter_clause,
)
from products.engineering_analytics.backend.logic.queries.pr_cost import query_workflow_window_costs

Granularity = Literal["hour", "day", "week"]

_LIMIT = 100
# Generous bound: _LIMIT workflows x at most ~366 daily buckets.
_BUCKET_LIMIT = 40000

# ClickHouse bucket function per granularity. Week starts Monday (mode 1).
_BUCKET_FN: dict[Granularity, str] = {
    "hour": "toStartOfHour(run_started_at)",
    "day": "toStartOfDay(run_started_at)",
    "week": "toStartOfWeek(run_started_at, 1)",
}
_BUCKET_STEP: dict[Granularity, timedelta] = {
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
}

# Which runs feed the p50/p95 duration percentiles.
_DURATION_CONDITION: dict[WorkflowHealthDurationFilter, str] = {
    WorkflowHealthDurationFilter.COMPLETED: "status = 'completed'",
    WorkflowHealthDurationFilter.SUCCESSFUL: "status = 'completed' AND conclusion = 'success'",
}

_SELECT = f"""
    SELECT
        repo_owner,
        repo_name,
        workflow_name,
        count() AS run_count,
        countIf(status = 'completed' AND conclusion = 'success') / nullIf(countIf(status = 'completed'), 0) AS success_rate,
        quantileIf(0.5)(duration_seconds, __DURATION_CONDITION__) AS p50_seconds,
        quantileIf(0.95)(duration_seconds, __DURATION_CONDITION__) AS p95_seconds,
        max(if(conclusion IN ('failure', 'timed_out'), run_started_at, NULL)) AS last_failure_at,
        countIf(status = 'completed') AS completed_count,
        argMaxIf(conclusion IN ('failure', 'timed_out'), run_started_at, status = 'completed') AS latest_failed,
        argMaxIf(conclusion, run_started_at, status = 'completed') AS latest_conclusion
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {{date_from}} __DATE_TO__ __BRANCH__ __RUN_SCOPE__
    GROUP BY repo_owner, repo_name, workflow_name
    ORDER BY run_count DESC
    LIMIT {_LIMIT}
"""

_BUCKET_SELECT = f"""
    SELECT
        repo_owner,
        repo_name,
        workflow_name,
        __BUCKET_FN__ AS bucket_start,
        count() AS run_count,
        countIf(status = 'completed') AS completed,
        countIf(status = 'completed' AND conclusion = 'success') AS successes,
        countIf(status = 'completed' AND conclusion IN ('failure', 'timed_out')) AS failures
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {{date_from}} __DATE_TO__ __BRANCH__ __RUN_SCOPE__
    GROUP BY repo_owner, repo_name, workflow_name, bucket_start
    LIMIT {_BUCKET_LIMIT}
"""


def query_workflow_health(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    branch: str | None = None,
    run_scope: WorkflowHealthRunScope = WorkflowHealthRunScope.ALL,
    duration_filter: WorkflowHealthDurationFilter = WorkflowHealthDurationFilter.COMPLETED,
) -> list[WorkflowHealthItem]:
    granularity = _pick_granularity(date_from, date_to)
    date_to_clause = "AND run_started_at <= {date_to}" if date_to is not None else ""
    placeholders: dict[str, ast.Expr] = {"date_from": ast.Constant(value=date_from)}
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)
    branch_clause = branch_filter_clause(branch, placeholders)
    run_scope_clause = run_scope_filter_clause(run_scope)
    duration_condition = _DURATION_CONDITION[duration_filter]

    runs_source = curated.run_source()

    def fill(template: str) -> str:
        return (
            template.replace("__RUNS_SOURCE__", runs_source)
            .replace("__DATE_TO__", date_to_clause)
            .replace("__BRANCH__", branch_clause)
            .replace("__RUN_SCOPE__", run_scope_clause)
            .replace("__DURATION_CONDITION__", duration_condition)
            .replace("__BUCKET_FN__", _BUCKET_FN[granularity])
        )

    response = curated.run(
        fill(_SELECT),
        query_type="engineering_analytics.workflow_health",
        placeholders=placeholders,
    )
    if not response.results:
        return []

    bucket_response = curated.run(
        fill(_BUCKET_SELECT),
        query_type="engineering_analytics.workflow_health_buckets",
        placeholders=placeholders,
    )
    buckets_by_workflow: dict[tuple[str, str, str], dict[datetime, WorkflowHealthBucket]] = {}
    for repo_owner, repo_name, workflow_name, bucket_start, run_count, completed, successes, failures in (
        bucket_response.results or []
    ):
        key = _normalize(bucket_start, granularity)
        buckets_by_workflow.setdefault((repo_owner, repo_name, workflow_name), {})[key] = WorkflowHealthBucket(
            bucket_start=key, run_count=run_count, completed=completed, successes=successes, failures=failures
        )

    cost_by_workflow = query_workflow_window_costs(
        curated=curated, date_from=date_from, date_to=date_to, branch=branch, run_scope=run_scope
    )
    window = _window_buckets(date_from, date_to, granularity)
    return [
        WorkflowHealthItem(
            repo=RepoRef(provider="github", owner=repo_owner, name=repo_name),
            workflow_name=workflow_name,
            run_count=run_count,
            success_rate=_to_opt_float(success_rate),
            p50_seconds=_to_opt_float(p50_seconds),
            p95_seconds=_to_opt_float(p95_seconds),
            last_failure_at=last_failure_at,
            # argMaxIf defaults to 0 when nothing completed; the completed_count guard tells
            # "latest run passed" apart from "no completed run yet".
            latest_run_failed=bool(latest_failed) if completed_count else None,
            # The raw conclusion of that latest completed run, so the UI can tell a real pass from a
            # cancelled/skipped run (both have latest_run_failed false). None when nothing completed.
            latest_run_conclusion=(latest_conclusion or None) if completed_count else None,
            granularity=granularity,
            buckets=[
                buckets_by_workflow.get((repo_owner, repo_name, workflow_name), {}).get(
                    bucket, WorkflowHealthBucket(bucket_start=bucket, run_count=0, completed=0, successes=0, failures=0)
                )
                for bucket in window
            ],
            billable_minutes=(
                cost_by_workflow[workflow_name].billable_seconds / 60 if workflow_name in cost_by_workflow else None
            ),
            estimated_cost_usd=(
                cost_by_workflow[workflow_name].estimated_cost_usd if workflow_name in cost_by_workflow else None
            ),
        )
        for repo_owner, repo_name, workflow_name, run_count, success_rate, p50_seconds, p95_seconds, last_failure_at, completed_count, latest_failed, latest_conclusion in response.results
    ]


def _pick_granularity(date_from: datetime, date_to: datetime | None) -> Granularity:
    """Hour for short windows, week for long ones — keeps the sparkline at a readable point count."""
    end = date_to or datetime.now(tz=date_from.tzinfo)
    span = end - date_from
    if span <= timedelta(hours=48):
        return "hour"
    if span <= timedelta(days=90):
        return "day"
    return "week"


def _window_buckets(date_from: datetime, date_to: datetime | None, granularity: Granularity) -> list[datetime]:
    end = date_to or datetime.now(tz=date_from.tzinfo)
    start = _normalize(date_from, granularity)
    end_aligned = _normalize(end, granularity)
    if end_aligned < start:
        return []
    step = _BUCKET_STEP[granularity]
    buckets: list[datetime] = []
    current = start
    while current <= end_aligned:
        buckets.append(current)
        current += step
    return buckets


def _normalize(value: datetime | date, granularity: Granularity) -> datetime:
    """Align a timestamp to its bucket start, tz-naive, so query rows and the zero-fill series key alike.

    ClickHouse can hand the bucket back as a ``date`` (date/week truncation) or a ``datetime``
    (hour truncation); widen the former so both sides key on the same type.
    """
    naive = value.replace(tzinfo=None) if isinstance(value, datetime) else datetime(value.year, value.month, value.day)
    if granularity == "hour":
        return naive.replace(minute=0, second=0, microsecond=0)
    midnight = naive.replace(hour=0, minute=0, second=0, microsecond=0)
    if granularity == "week":
        return midnight - timedelta(days=midnight.weekday())
    return midnight


def _to_opt_float(value: float | None) -> float | None:
    # quantileIf over an empty window returns NaN; nullIf division returns None.
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)
