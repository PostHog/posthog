import re
import math
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from posthog.dataclasses import frozen
from posthog.hogql_queries.apply_dashboard_filters import resolve_effective_dashboard_filters
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team, User

from products.product_analytics.backend.facade.contracts import InsightDashboardContext, InsightSeries

ADDITIVE_MATH = {"total", "sum", "first_time_for_user", "first_matching_event_for_user"}
UNCHARTED_DISPLAYS = {
    "ActionsTable",
    "ActionsPie",
    "BoldNumber",
    "WorldMap",
    "ActionsBarValue",
    "ActionsLineGraphCumulative",
}
LOOKBACK = {"day": "-56d", "week": "-16w", "month": "-24m"}
DATE_FILTERS = ("date_from", "date_to", "explicitDate", "interval", "compareFilter")
EXECUTION_MODE = ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE


@frozen
class TimeSeries:
    series: dict[str, list[tuple[date, float]]]
    averaged: list[str]
    period: str


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value[:10])
    return None


def _date_column(width: int, rows: list[list[Any]]) -> int | None:
    for index in range(width):
        present = [row[index] for row in rows if row[index] is not None]
        if present and sum(1 for value in present if _parse_date(value)) >= 0.8 * len(present):
            return index
    return None


def _run(
    team: Team,
    user: User,
    source: dict[str, Any],
    filters: dict[str, Any] | None,
    variables: dict[str, Any] | None,
) -> dict[str, Any]:
    from posthog.api.services.query import process_query_dict  # noqa: PLC0415

    response = process_query_dict(
        team,
        source,
        dashboard_filters_json=filters,
        variables_override_json=variables,
        execution_mode=EXECUTION_MODE,
        user=user,
    )
    return response.model_dump() if isinstance(response, BaseModel) else response


def _table_series(columns: list[str], rows: list[list[Any]]) -> TimeSeries | None:
    date_index = _date_column(len(columns), rows)
    if date_index is None:
        return None
    numbers = [
        i
        for i in range(len(columns))
        if i != date_index and all(isinstance(r[i], int | float | Decimal) or r[i] is None for r in rows)
    ]
    texts = [i for i in range(len(columns)) if i not in numbers and i != date_index]
    if not numbers or len(texts) > 1:
        return None
    sums: defaultdict[str, defaultdict[date, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        day = _parse_date(row[date_index])
        if day is None:
            continue
        for index in numbers[:1] if texts else numbers:
            value = float(row[index] or 0)
            if math.isfinite(value):
                sums[str(row[texts[0]]) if texts else columns[index]][day] += value
    days = sorted({d for values in sums.values() for d in values})
    gap = min(((b - a).days for a, b in zip(days, days[1:])), default=0)
    if gap > 32:
        return None
    return TimeSeries(
        series={name: sorted(values.items()) for name, values in sums.items() if name and name != "None"},
        averaged=[],
        period="day" if gap <= 1 else "week" if gap <= 8 else "month",
    )


def _trends_series(
    team: Team,
    user: User,
    source: dict[str, Any],
    filters: dict[str, Any] | None,
    variables: dict[str, Any] | None,
) -> TimeSeries | None:
    trends = source.get("trendsFilter") or {}
    if trends.get("display") in UNCHARTED_DISPLAYS:
        return None
    interval = source.get("interval") or "day"
    if interval not in LOOKBACK:
        interval = "day"
    bounded = {key: value for key, value in source.items() if key != "compareFilter"}
    bounded.update(interval=interval, dateRange={"date_from": LOOKBACK[interval]})
    response = _run(team, user, bounded, filters, variables)
    formula = bool(trends.get("formula") or trends.get("formulas") or trends.get("formulaNodes"))
    several = len(source.get("series") or []) > 1
    series: dict[str, list[tuple[date, float]]] = {}
    averaged: list[str] = []
    for result in response.get("results") or []:
        if not result.get("days"):
            continue
        action = result.get("action") or {}
        label = str(action.get("custom_name") or result.get("label") or "Series")
        breakdown = result.get("breakdown_value")
        if breakdown not in (None, ""):
            value = ", ".join(str(b) for b in breakdown) if isinstance(breakdown, list) else str(breakdown)
            label = f"{label} · {value}" if several else value
        while label in series:
            label += " (2)"
        series[label] = [
            (date.fromisoformat(str(d)[:10]), float(v or 0)) for d, v in zip(result["days"], result["data"])
        ]
        if formula or (action.get("math") or "total") not in ADDITIVE_MATH:
            averaged.append(label)
    return TimeSeries(series=series, averaged=averaged, period=interval)


def insight_series(
    team: Team,
    user: User,
    *,
    short_id: str,
    name: str | None,
    query: dict[str, Any],
    dashboard: InsightDashboardContext | None,
) -> InsightSeries | None:
    filters: dict[str, Any] | None = None
    variables: dict[str, Any] | None = None
    if dashboard is not None:
        effective = resolve_effective_dashboard_filters(query, dashboard.filters, dashboard.tile_filters)
        query = effective.query
        filters = {key: value for key, value in (effective.filters or {}).items() if key not in DATE_FILTERS}
        variables = dashboard.variables
    source = query.get("source", query)
    kind = source.get("kind")
    if kind == "TrendsQuery":
        found = _trends_series(team, user, source, filters, variables)
    elif kind == "HogQLQuery" and "{filters}" in (source.get("query") or ""):
        bounded = {**source, "filters": {**(source.get("filters") or {}), "dateRange": {"date_from": LOOKBACK["day"]}}}
        response = _run(team, user, bounded, filters, variables)
        found = _table_series(response.get("columns") or [], response.get("results") or [])
    else:
        return None
    if found is None or not found.series:
        return None
    display = source.get("trendsFilter") or {}
    nodes = source.get("series") or []
    node = nodes[0] if len(nodes) == 1 else {}
    return InsightSeries(
        short_id=short_id,
        name=name,
        series=found.series,
        period=found.period,
        averaged_series=found.averaged,
        event_name=str(node.get("custom_name") or node.get("event") or node.get("name") or ""),
        value_format=display.get("aggregationAxisFormat"),
        value_prefix=display.get("aggregationAxisPrefix"),
        value_postfix=display.get("aggregationAxisPostfix"),
        decimal_places=display.get("decimalPlaces"),
    )
