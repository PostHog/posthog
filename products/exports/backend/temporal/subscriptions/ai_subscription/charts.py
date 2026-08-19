import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from products.exports.backend.facade.api import render_png_export
from products.exports.backend.temporal.subscriptions.ai_subscription.schemas import (
    ALLOWED_CHART_DISPLAYS,
    CONTINUOUS_CHART_DISPLAYS,
    MAX_CHART_CATEGORIES,
    MAX_CHART_SERIES,
    MIN_CHART_CATEGORIES,
    MIN_CHART_ROWS,
    StepChart,
)

logger = structlog.get_logger(__name__)

# Charts change what every AI report looks like and add a render plus a query to each delivery, so
# the rollout is per-team rather than a deploy.
AI_REPORT_CHARTS_FEATURE_FLAG_KEY = "ai-report-charts"


def charts_enabled(team: Team, user: User) -> bool:
    """Whether this team renders charts. Fails closed: a flag service error means text-only."""
    if not getattr(user, "distinct_id", None):
        return False
    org_id = str(team.organization_id)
    try:
        return bool(
            posthoganalytics.feature_enabled(
                AI_REPORT_CHARTS_FEATURE_FLAG_KEY,
                str(user.distinct_id),
                groups={"organization": org_id},
                group_properties={"organization": {"id": org_id}},
                only_evaluate_locally=False,
            )
        )
    except Exception:
        logger.warning("ai_report.chart_flag_lookup_failed", team_id=team.id, exc_info=True)
        return False


# Drop reasons that mean the spec itself is wrong, so re-planning can produce a better one. Every
# other reason describes this run's data (an empty week, a breakdown that grew past the bar cap) and
# would recur on a frozen plan forever, so those must not block freezing.
SPEC_INVALID_DROP_REASONS = frozenset({"missing_columns", "x_and_y_identical", "non_numeric_series"})

# Cap simultaneous browserless renders per report, mirroring the per-report ClickHouse step cap.
_MAX_CONCURRENT_RENDERS = 3
# Renders block their thread for the whole child export workflow, and the per-render timeout cannot
# reclaim it (asgiref cannot cancel a sync callable that started). On the loop's default executor
# they would sit alongside the blocking HogQL executions of every other activity on this worker, so
# they get their own bounded pool and can only ever crowd out each other.
_RENDER_EXECUTOR = ThreadPoolExecutor(max_workers=_MAX_CONCURRENT_RENDERS, thread_name_prefix="ai-report-chart")
# Per-render ceiling, below the exporter's own 90s RENDER_TIMEOUT so a stuck render is dropped here
# rather than holding a slot for the full export timeout.
_RENDER_TIMEOUT_SECONDS = 75.0
# Whole-phase ceiling. Deliberately above the worst case (ceil(MAX_CHARTS_PER_REPORT /
# _MAX_CONCURRENT_RENDERS) waves x _RENDER_TIMEOUT_SECONDS) so ordinary dispatch overhead — the
# asset insert, a Temporal connect, browserless queueing — cannot turn a full report into no charts.
_CHART_PHASE_BUDGET_SECONDS = 210.0


@frozen
class ValidatedChart:
    spec: StepChart
    # The executed HogQL, window placeholders already resolved — never the planner's template.
    hogql: str
    title: str
    step_index: int


def validate_chart(
    spec: StepChart,
    response: Any,
    *,
    hogql: str,
    title: str,
    step_index: int,
) -> tuple[Optional[ValidatedChart], Optional[str]]:
    """Check a planner-emitted chart spec against the result its step actually returned.

    Returns the chart, or None with a short reason for the diagnostics record. Never raises: a
    chart is an addition to a report, so anything unexpected here drops the picture, not the report.
    """
    rows = response.get("results") if isinstance(response, dict) else None
    if not isinstance(rows, list) or not rows:
        return None, "no_results"

    # The planner is steered by the field descriptions, not bound by them, so the real limits are
    # enforced here where a violation costs the chart instead of the whole plan.
    if spec.display not in ALLOWED_CHART_DISPLAYS:
        return None, "unsupported_display"
    if not spec.y_columns or len(spec.y_columns) > MAX_CHART_SERIES:
        return None, "unsupported_series_count"
    # A result the query runner truncated is not the series the planner asked for, and nothing on
    # the chart would say so.
    if response.get("hasMore"):
        return None, "truncated_result"

    columns = response.get("columns")
    if not isinstance(columns, list):
        return None, "missing_columns"
    column_names = [str(column) for column in columns]
    if not {spec.x_column, *spec.y_columns}.issubset(set(column_names)):
        return None, "missing_columns"

    # Plotting a column against itself is never a chart. It is what a planner emits when it marks a
    # single scalar (a rate, a growth percentage) as chartable.
    if spec.x_column in spec.y_columns:
        return None, "x_and_y_identical"

    # The planner is told every y column must be numeric, but nothing enforced it, so a text column
    # shipped as a blank chart counted as a success. `types` is [[name, clickhouse_type], ...].
    numeric_columns = _numeric_column_names(response.get("types"))
    if numeric_columns is not None and not set(spec.y_columns).issubset(numeric_columns):
        return None, "non_numeric_series"

    if spec.display in CONTINUOUS_CHART_DISPLAYS:
        if len(rows) < MIN_CHART_ROWS:
            return None, "too_few_rows"
    elif len(rows) < MIN_CHART_CATEGORIES:
        return None, "too_few_rows"
    elif _distinct_count(rows, column_names.index(spec.x_column)) > MAX_CHART_CATEGORIES:
        return None, "too_many_categories"

    return ValidatedChart(spec=spec, hogql=hogql, title=title, step_index=step_index), None


def _numeric_column_names(types: Any) -> Optional[set[str]]:
    """Column names whose ClickHouse type is numeric, or None when the shape is unreadable.

    None means "cannot tell" and the caller skips the check, so an unexpected `types` shape costs a
    guard rather than every chart.
    """
    if not isinstance(types, list) or not types:
        return None
    numeric: set[str] = set()
    for entry in types:
        if not isinstance(entry, list | tuple) or len(entry) < 2:
            return None
        name, clickhouse_type = str(entry[0]), str(entry[1])
        # Nullable(Int64), LowCardinality(Float64) and friends carry the inner type in the name.
        if any(token in clickhouse_type for token in ("Int", "Float", "Decimal", "UInt")):
            numeric.add(name)
    return numeric


def _distinct_count(rows: list[Any], index: int) -> int:
    values = set()
    for row in rows:
        if isinstance(row, list | tuple) and index < len(row):
            values.add(str(row[index]))
    return len(values)


@frozen
class RenderedChart:
    export_asset_id: int
    title: str
    step_index: int


def build_export_context(chart: ValidatedChart) -> dict:
    """The ad-hoc export payload for one chart. Multi-series charts turn the legend on: the
    exporter's own legend paths are Trends-only, so a SQL chart without it draws unlabeled lines."""
    chart_settings: dict[str, Any] = {
        "xAxis": {"column": chart.spec.x_column},
        "yAxis": [{"column": column} for column in chart.spec.y_columns],
    }
    if len(chart.spec.y_columns) > 1:
        chart_settings["showLegend"] = True
    return {
        # Pins the render to the same row limits the step ran under. Without it the render clamps at
        # LimitContext.QUERY (50k rows) while the step validated at POSTHOG_AI (500), so the chart
        # could plot rows the report never saw — and the differing cache key guaranteed a second
        # full execution rather than a hit on the step's result.
        "limit_context": "posthog_ai",
        "source": {
            "kind": "DataVisualizationNode",
            "source": {"kind": "HogQLQuery", "query": chart.hogql},
            "display": chart.spec.display,
            "chartSettings": chart_settings,
        },
    }


async def render_charts(
    charts: list[ValidatedChart],
    *,
    team: Team,
    user: User,
) -> tuple[list[RenderedChart], list[tuple[int, str]]]:
    """Render each chart to a PNG export, returning the assets and one (step index, reason) per failure.

    Never raises. A report that cannot draw its charts ships as text, the way a report whose steps
    failed already degrades.
    """
    if not charts:
        return [], []

    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_RENDERS)

    async def render_one(chart: ValidatedChart) -> tuple[Optional[RenderedChart], Optional[tuple[int, str]]]:
        async with semaphore:
            try:
                # render_png_export wraps async_to_sync internally, so it cannot be awaited directly
                # from this activity's event loop.
                asset, png = await asyncio.wait_for(
                    database_sync_to_async(render_png_export, thread_sensitive=False, executor=_RENDER_EXECUTOR)(
                        team=team,
                        created_by=user,
                        export_context=build_export_context(chart),
                    ),
                    timeout=_RENDER_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                # Cancelling this does not stop the worker thread: asgiref cannot cancel a sync
                # callable that already started, so the render finishes and writes an asset nothing
                # references. The timeout frees the report, not the browserless worker.
                logger.warning("ai_report.chart_render_timed_out", step_index=chart.step_index)
                return None, (chart.step_index, "render_timed_out")
            except Exception:
                logger.warning("ai_report.chart_render_error", step_index=chart.step_index, exc_info=True)
                return None, (chart.step_index, "render_error")
            if png is None:
                logger.warning("ai_report.chart_render_failed", step_index=chart.step_index, error=str(asset.exception))
                return None, (chart.step_index, "render_failed")
            return RenderedChart(export_asset_id=asset.id, title=chart.title, step_index=chart.step_index), None

    tasks = {asyncio.create_task(render_one(chart)): chart for chart in charts}
    # wait(), not wait_for() over a gather: a phase that overruns must keep the charts that already
    # rendered rather than discarding paid-for work and reporting them all as failures.
    done, pending = await asyncio.wait(tasks.keys(), timeout=_CHART_PHASE_BUDGET_SECONDS)
    for task in pending:
        task.cancel()
    if pending:
        logger.warning("ai_report.chart_phase_budget_exhausted", abandoned=len(pending), chart_count=len(charts))

    rendered: list[RenderedChart] = []
    failures: list[tuple[int, str]] = [(tasks[task].step_index, "budget_exhausted") for task in pending]
    for task in done:
        # A task that raised is a bug in render_one, which catches everything it expects; treat it
        # as a lost chart rather than letting it escape and cost the report.
        if task.exception() is not None:
            logger.warning("ai_report.chart_render_error", step_index=tasks[task].step_index, exc_info=True)
            failures.append((tasks[task].step_index, "render_error"))
            continue
        chart, failure = task.result()
        if chart is not None:
            rendered.append(chart)
        if failure is not None:
            failures.append(failure)
    # Keep report order stable regardless of which render finished first.
    rendered.sort(key=lambda item: item.step_index)
    failures.sort(key=lambda item: item[0])
    return rendered, failures
