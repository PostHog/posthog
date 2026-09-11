import asyncio
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum
from typing import Any, Literal, Optional, TypedDict

import structlog

from posthog.hogql.type_system import parse_clickhouse_type

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.ph_client import feature_enabled_or_false
from posthog.sync import database_sync_to_async

from products.exports.backend.facade.api import RENDER_TIMEOUT, render_png_export
from products.exports.backend.temporal.subscriptions.ai_subscription.report_context import (
    ContextVisualCandidate,
    user_can_access_context_visual,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.schemas import (
    ALLOWED_CHART_DISPLAYS,
    CONTINUOUS_CHART_DISPLAYS,
    MAX_CHART_CATEGORIES,
    MAX_CHART_SERIES,
    MAX_CHARTS_PER_REPORT,
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
    CONTEXT_ACCESS_REVOKED = "context_access_revoked"


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
    source: Literal["generated"] = "generated"


@frozen
class RenderedContextChart:
    export_asset_id: int
    title: str
    context_ref: str
    insight_id: int
    dashboard_id: int | None = None
    dashboard_tile_id: int | None = None
    source: Literal["context"] = "context"

    def __post_init__(self) -> None:
        if (self.dashboard_id is None) != (self.dashboard_tile_id is None):
            raise ValueError("Dashboard and tile identifiers must be paired")


type RenderedChartResult = RenderedChart | RenderedContextChart


class GeneratedChartSnapshot(TypedDict):
    source: Literal["generated"]
    export_asset_id: int
    title: str
    step_index: int


class ContextChartSnapshot(TypedDict):
    source: Literal["context"]
    export_asset_id: int
    title: str
    context_ref: str
    insight_id: int
    dashboard_id: int | None
    dashboard_tile_id: int | None


type RenderedChartSnapshot = GeneratedChartSnapshot | ContextChartSnapshot


def serialize_rendered_chart(chart: RenderedChartResult) -> RenderedChartSnapshot:
    if isinstance(chart, RenderedContextChart):
        return {
            "source": "context",
            "export_asset_id": chart.export_asset_id,
            "title": chart.title,
            "context_ref": chart.context_ref,
            "insight_id": chart.insight_id,
            "dashboard_id": chart.dashboard_id,
            "dashboard_tile_id": chart.dashboard_tile_id,
        }
    return {
        "source": "generated",
        "export_asset_id": chart.export_asset_id,
        "title": chart.title,
        "step_index": chart.step_index,
    }


@frozen
class ChartRenderFailure:
    step_index: int
    reason: ChartFailureReason


@frozen
class ContextChartRenderFailure:
    context_ref: str
    reason: ChartFailureReason


type AnyChartRenderFailure = ChartRenderFailure | ContextChartRenderFailure


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
        "title": chart.title,
        "source": {
            "kind": "DataVisualizationNode",
            "source": {"kind": "HogQLQuery", "query": chart.hogql},
            "display": chart.spec.display,
            "chartSettings": chart_settings,
        },
    }


def build_context_export_context(candidate: ContextVisualCandidate) -> dict:
    return {
        "limit_context": "posthog_ai",
        "title": candidate.title,
        "source": candidate.visualization.model_dump(mode="json"),
    }


async def render_charts(
    charts: list[ValidatedChart],
    *,
    context_visuals: Sequence[ContextVisualCandidate] = (),
    team: Team,
    user: User,
) -> tuple[list[RenderedChartResult], list[AnyChartRenderFailure]]:
    bounded_context = list(context_visuals[:MAX_CHARTS_PER_REPORT])
    generated_slots = max(0, MAX_CHARTS_PER_REPORT - len(bounded_context))
    attempts: list[ValidatedChart | ContextVisualCandidate] = [*bounded_context, *charts[:generated_slots]]
    if not attempts:
        return [], []

    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_RENDERS)

    def failure_for(
        attempt: ValidatedChart | ContextVisualCandidate, reason: ChartFailureReason
    ) -> AnyChartRenderFailure:
        if isinstance(attempt, ContextVisualCandidate):
            return ContextChartRenderFailure(context_ref=attempt.ref, reason=reason)
        return ChartRenderFailure(step_index=attempt.step_index, reason=reason)

    async def render_one(
        attempt: ValidatedChart | ContextVisualCandidate,
    ) -> tuple[Optional[RenderedChartResult], Optional[AnyChartRenderFailure]]:
        async with semaphore:
            if isinstance(attempt, ContextVisualCandidate):
                can_access = await database_sync_to_async(user_can_access_context_visual, thread_sensitive=False)(
                    team=team, user=user, candidate=attempt
                )
                if not can_access:
                    logger.warning("ai_report.context_chart_access_revoked", context_ref=attempt.ref)
                    return None, failure_for(attempt, ChartFailureReason.CONTEXT_ACCESS_REVOKED)
                export_context = build_context_export_context(attempt)
            else:
                export_context = build_export_context(attempt)
            try:
                asset, png = await asyncio.wait_for(
                    database_sync_to_async(render_png_export, thread_sensitive=False, executor=_RENDER_EXECUTOR)(
                        team=team,
                        created_by=user,
                        export_context=export_context,
                    ),
                    timeout=_RENDER_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                logger.warning("ai_report.chart_render_timed_out")
                return None, failure_for(attempt, ChartFailureReason.RENDER_TIMED_OUT)
            except Exception:
                logger.warning("ai_report.chart_render_error", exc_info=True)
                return None, failure_for(attempt, ChartFailureReason.RENDER_ERROR)
            if png is None:
                logger.warning("ai_report.chart_render_failed", error=str(asset.exception))
                return None, failure_for(attempt, ChartFailureReason.RENDER_FAILED)
            if isinstance(attempt, ContextVisualCandidate):
                return (
                    RenderedContextChart(
                        export_asset_id=asset.id,
                        title=attempt.title,
                        context_ref=attempt.ref,
                        insight_id=attempt.insight_id,
                        dashboard_id=attempt.dashboard_id,
                        dashboard_tile_id=attempt.dashboard_tile_id,
                    ),
                    None,
                )
            return RenderedChart(export_asset_id=asset.id, title=attempt.title, step_index=attempt.step_index), None

    tasks = {asyncio.create_task(render_one(attempt)): (index, attempt) for index, attempt in enumerate(attempts)}
    done, pending = await asyncio.wait(tasks.keys(), timeout=_CHART_PHASE_BUDGET_SECONDS)
    for task in pending:
        task.cancel()
    if pending:
        logger.warning("ai_report.chart_phase_budget_exhausted", abandoned=len(pending), chart_count=len(attempts))

    rendered_with_order: list[tuple[int, RenderedChartResult]] = []
    failures_with_order: list[tuple[int, AnyChartRenderFailure]] = [
        (tasks[task][0], failure_for(tasks[task][1], ChartFailureReason.BUDGET_EXHAUSTED)) for task in pending
    ]
    for task in done:
        order, attempt = tasks[task]
        if task.exception() is not None:
            logger.warning("ai_report.chart_render_error", exc_info=True)
            failures_with_order.append((order, failure_for(attempt, ChartFailureReason.RENDER_ERROR)))
            continue
        chart, failure = task.result()
        if chart is not None:
            rendered_with_order.append((order, chart))
        if failure is not None:
            failures_with_order.append((order, failure))
    rendered_with_order.sort(key=lambda item: item[0])
    failures_with_order.sort(key=lambda item: item[0])
    return [chart for _, chart in rendered_with_order], [failure for _, failure in failures_with_order]
