from typing import Any, Optional

import structlog

from posthog.dataclasses import frozen

from products.exports.backend.temporal.subscriptions.ai_subscription.schemas import (
    MAX_CHART_CATEGORIES,
    MIN_CHART_ROWS,
    StepChart,
)

logger = structlog.get_logger(__name__)

# Displays whose x axis is a continuous run of points, so a chart of one or two rows reads as noise.
_CONTINUOUS_DISPLAYS = {"ActionsLineGraph", "ActionsAreaGraph"}


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

    if spec.display in _CONTINUOUS_DISPLAYS:
        if len(rows) < MIN_CHART_ROWS:
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
