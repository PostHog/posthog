import asyncio
from typing import Any, Optional

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from products.exports.backend.facade.api import render_png_export
from products.exports.backend.temporal.subscriptions.ai_subscription.schemas import (
    MAX_CHART_CATEGORIES,
    MIN_CHART_CATEGORIES,
    MIN_CHART_ROWS,
    StepChart,
)

logger = structlog.get_logger(__name__)

# Displays whose x axis is a continuous run of points, so a chart of one or two rows reads as noise.
_CONTINUOUS_DISPLAYS = {"ActionsLineGraph", "ActionsAreaGraph"}

# A single render holds a browserless worker for up to 90s. Bound the whole phase well inside the
# generate activity's 10-minute start_to_close_timeout: that activity retries three times and each
# retry re-runs the LLM pipeline, so a slow render must never be what times it out.
_CHART_PHASE_BUDGET_SECONDS = 180.0
# Cap simultaneous browserless renders per report, mirroring the per-report ClickHouse step cap.
_MAX_CONCURRENT_RENDERS = 3


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

    if spec.display in _CONTINUOUS_DISPLAYS:
        if len(rows) < MIN_CHART_ROWS:
            return None, "too_few_rows"
    elif len(rows) < MIN_CHART_CATEGORIES:
        return None, "too_few_rows"
    elif _distinct_count(rows, column_names.index(spec.x_column)) > MAX_CHART_CATEGORIES:
        return None, "too_many_categories"

    return ValidatedChart(spec=spec, hogql=hogql, title=title, step_index=step_index), None


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
        "source": {
            "kind": "DataVisualizationNode",
            "source": {"kind": "HogQLQuery", "query": chart.hogql},
            "display": chart.spec.display,
            "chartSettings": chart_settings,
        }
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
                asset, png = await database_sync_to_async(render_png_export, thread_sensitive=False)(
                    team=team,
                    created_by=user,
                    export_context=build_export_context(chart),
                )
            except Exception:
                logger.warning("ai_report.chart_render_error", step_index=chart.step_index, exc_info=True)
                return None, (chart.step_index, "render_error")
            if png is None:
                logger.warning("ai_report.chart_render_failed", step_index=chart.step_index, error=str(asset.exception))
                return None, (chart.step_index, "render_failed")
            return RenderedChart(export_asset_id=asset.id, title=chart.title, step_index=chart.step_index), None

    try:
        outcomes = await asyncio.wait_for(
            asyncio.gather(*(render_one(chart) for chart in charts)),
            timeout=_CHART_PHASE_BUDGET_SECONDS,
        )
    except TimeoutError:
        logger.warning("ai_report.chart_phase_budget_exhausted", chart_count=len(charts))
        # The budget bounds the phase, not a single chart, so every chart in flight is lost.
        return [], [(chart.step_index, "budget_exhausted") for chart in charts]

    rendered = [chart for chart, _ in outcomes if chart is not None]
    failures = [failure for _, failure in outcomes if failure is not None]
    return rendered, failures
