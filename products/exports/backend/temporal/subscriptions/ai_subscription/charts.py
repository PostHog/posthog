import asyncio
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum
from typing import Any, Optional

import structlog

from posthog.hogql.type_system import parse_clickhouse_type

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.ph_client import feature_enabled_or_false
from posthog.sync import database_sync_to_async

from products.exports.backend.facade.api import RENDER_TIMEOUT, render_png_export
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

AI_REPORT_CHARTS_FEATURE_FLAG_KEY = "ai-report-charts"

_MAX_CONCURRENT_RENDERS = 5
_RENDER_EXECUTOR = ThreadPoolExecutor(max_workers=_MAX_CONCURRENT_RENDERS, thread_name_prefix="ai-report-chart")
_RENDER_TIMEOUT_SECONDS = RENDER_TIMEOUT.total_seconds() + 10
_CHART_PHASE_BUDGET_SECONDS = 210.0

_NUMERIC_TYPE_FAMILIES = frozenset({"integer", "float", "decimal"})


class ChartFailureReason(StrEnum):
    NO_RESULTS = "no_results"
    UNSUPPORTED_DISPLAY = "unsupported_display"
    UNSUPPORTED_SERIES_COUNT = "unsupported_series_count"
    TRUNCATED_RESULT = "truncated_result"
    MISSING_COLUMNS = "missing_columns"
    X_AND_Y_IDENTICAL = "x_and_y_identical"
    NON_NUMERIC_SERIES = "non_numeric_series"
    TOO_FEW_ROWS = "too_few_rows"
    TOO_MANY_CATEGORIES = "too_many_categories"
    VALIDATION_ERROR = "validation_error"
    RENDER_TIMED_OUT = "render_timed_out"
    RENDER_ERROR = "render_error"
    RENDER_FAILED = "render_failed"
    BUDGET_EXHAUSTED = "budget_exhausted"


SPEC_INVALID_DROP_REASONS = frozenset(
    {
        ChartFailureReason.MISSING_COLUMNS,
        ChartFailureReason.X_AND_Y_IDENTICAL,
        ChartFailureReason.NON_NUMERIC_SERIES,
    }
)


@frozen
class ValidatedChart:
    spec: StepChart
    hogql: str
    title: str
    step_index: int


@frozen
class RenderedChart:
    export_asset_id: int
    title: str
    step_index: int


@frozen
class ChartRenderFailure:
    step_index: int
    reason: ChartFailureReason


def charts_enabled(team: Team, user: User) -> bool:
    if not getattr(user, "distinct_id", None):
        return False
    org_id = str(team.organization_id)
    return feature_enabled_or_false(
        AI_REPORT_CHARTS_FEATURE_FLAG_KEY,
        str(user.distinct_id),
        groups={"organization": org_id},
        group_properties={"organization": {"id": org_id}},
    )


def validate_chart(
    spec: StepChart,
    response: Any,
    *,
    hogql: str,
    title: str,
    step_index: int,
) -> tuple[Optional[ValidatedChart], Optional[ChartFailureReason]]:
    rows = response.get("results") if isinstance(response, dict) else None
    if not isinstance(rows, list) or not rows:
        return None, ChartFailureReason.NO_RESULTS

    if spec.display not in ALLOWED_CHART_DISPLAYS:
        return None, ChartFailureReason.UNSUPPORTED_DISPLAY
    if not spec.y_columns or len(spec.y_columns) > MAX_CHART_SERIES:
        return None, ChartFailureReason.UNSUPPORTED_SERIES_COUNT
    if response.get("hasMore"):
        return None, ChartFailureReason.TRUNCATED_RESULT

    columns = response.get("columns")
    if not isinstance(columns, list):
        return None, ChartFailureReason.MISSING_COLUMNS
    column_names = [str(column) for column in columns]
    if not {spec.x_column, *spec.y_columns}.issubset(set(column_names)):
        return None, ChartFailureReason.MISSING_COLUMNS

    if spec.x_column in spec.y_columns:
        return None, ChartFailureReason.X_AND_Y_IDENTICAL

    numeric_columns = _numeric_column_names(response.get("types"))
    if numeric_columns is not None and not set(spec.y_columns).issubset(numeric_columns):
        return None, ChartFailureReason.NON_NUMERIC_SERIES

    if spec.display in CONTINUOUS_CHART_DISPLAYS:
        if len(rows) < MIN_CHART_ROWS:
            return None, ChartFailureReason.TOO_FEW_ROWS
    elif len(rows) < MIN_CHART_CATEGORIES:
        return None, ChartFailureReason.TOO_FEW_ROWS
    elif _distinct_count(rows, column_names.index(spec.x_column)) > MAX_CHART_CATEGORIES:
        return None, ChartFailureReason.TOO_MANY_CATEGORIES

    return ValidatedChart(spec=spec, hogql=hogql, title=title, step_index=step_index), None


def _numeric_column_names(types: Any) -> Optional[set[str]]:
    if not isinstance(types, list) or not types:
        return None
    numeric: set[str] = set()
    for entry in types:
        if not isinstance(entry, list | tuple) or len(entry) < 2:
            return None
        name, clickhouse_type = str(entry[0]), str(entry[1])
        if parse_clickhouse_type(clickhouse_type).family in _NUMERIC_TYPE_FAMILIES:
            numeric.add(name)
    return numeric


def _distinct_count(rows: list[Any], index: int) -> int:
    values = set()
    for row in rows:
        if isinstance(row, list | tuple) and index < len(row):
            values.add(str(row[index]))
    return len(values)


def build_export_context(chart: ValidatedChart) -> dict:
    chart_settings: dict[str, Any] = {
        "xAxis": {"column": chart.spec.x_column},
        "yAxis": [{"column": column} for column in chart.spec.y_columns],
    }
    if len(chart.spec.y_columns) > 1:
        chart_settings["showLegend"] = True
    return {
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
) -> tuple[list[RenderedChart], list[ChartRenderFailure]]:
    if not charts:
        return [], []

    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_RENDERS)

    async def render_one(chart: ValidatedChart) -> tuple[Optional[RenderedChart], Optional[ChartRenderFailure]]:
        async with semaphore:
            try:
                asset, png = await asyncio.wait_for(
                    database_sync_to_async(render_png_export, thread_sensitive=False, executor=_RENDER_EXECUTOR)(
                        team=team,
                        created_by=user,
                        export_context=build_export_context(chart),
                    ),
                    timeout=_RENDER_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                logger.warning("ai_report.chart_render_timed_out", step_index=chart.step_index)
                return None, ChartRenderFailure(step_index=chart.step_index, reason=ChartFailureReason.RENDER_TIMED_OUT)
            except Exception:
                logger.warning("ai_report.chart_render_error", step_index=chart.step_index, exc_info=True)
                return None, ChartRenderFailure(step_index=chart.step_index, reason=ChartFailureReason.RENDER_ERROR)
            if png is None:
                logger.warning("ai_report.chart_render_failed", step_index=chart.step_index, error=str(asset.exception))
                return None, ChartRenderFailure(step_index=chart.step_index, reason=ChartFailureReason.RENDER_FAILED)
            return RenderedChart(export_asset_id=asset.id, title=chart.title, step_index=chart.step_index), None

    tasks = {asyncio.create_task(render_one(chart)): chart for chart in charts}
    done, pending = await asyncio.wait(tasks.keys(), timeout=_CHART_PHASE_BUDGET_SECONDS)
    for task in pending:
        task.cancel()
    if pending:
        logger.warning("ai_report.chart_phase_budget_exhausted", abandoned=len(pending), chart_count=len(charts))

    rendered: list[RenderedChart] = []
    failures: list[ChartRenderFailure] = [
        ChartRenderFailure(step_index=tasks[task].step_index, reason=ChartFailureReason.BUDGET_EXHAUSTED)
        for task in pending
    ]
    for task in done:
        if task.exception() is not None:
            logger.warning("ai_report.chart_render_error", step_index=tasks[task].step_index, exc_info=True)
            failures.append(
                ChartRenderFailure(step_index=tasks[task].step_index, reason=ChartFailureReason.RENDER_ERROR)
            )
            continue
        chart, failure = task.result()
        if chart is not None:
            rendered.append(chart)
        if failure is not None:
            failures.append(failure)
    rendered.sort(key=lambda item: item.step_index)
    failures.sort(key=lambda item: item.step_index)
    return rendered, failures
