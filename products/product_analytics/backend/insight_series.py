import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from posthog.hogql_queries.apply_dashboard_filters import resolve_effective_dashboard_filters
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team, User
from posthog.week_start_day import WeekStartDay

from products.product_analytics.backend.facade.contracts import InsightDashboardContext, InsightSeries

ADDITIVE_MATH = {
    "total",
    "sum",
    "first_time_for_user",
    "first_matching_event_for_user",
    "first_time_for_group",
    "first_matching_event_for_group",
}
UNCHARTED_DISPLAYS = {
    "ActionsTable",
    "ActionsPie",
    "BoldNumber",
    "WorldMap",
    "ActionsBarValue",
    "ActionsLineGraphCumulative",
    "SlopeGraph",
}
CHARTED_SQL_DISPLAYS = {"ActionsLineGraph", "ActionsBar", "ActionsStackedBar", "ActionsAreaGraph"}
LOOKBACK = {"day": "-56d", "week": "-16w", "month": "-24m"}
DATE_FILTERS = ("date_from", "date_to", "explicitDate", "interval", "compareFilter")
EXECUTION_MODE = ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE


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


def _value_key(result: dict[str, Any], position: int) -> str:
    order = (result.get("action") or {}).get("order")
    payload: dict[str, Any] = {
        "series": order if isinstance(order, int) else f"formula{position + 1}" if position else "formula"
    }
    if "breakdown_value" in result:
        breakdown = result["breakdown_value"]
        payload["breakdown_value"] = breakdown if isinstance(breakdown, list) else [breakdown]
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _visible(trends: dict[str, Any], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    customizations = trends.get("resultCustomizations") or {}
    if not customizations:
        return results
    by_position = trends.get("resultCustomizationBy") == "position"
    ranked = sorted(range(len(results)), key=lambda i: (results[i].get("action") or {}).get("order") or 0)
    positions = {index: rank for rank, index in enumerate(ranked)}
    return [
        result
        for index, result in enumerate(results)
        if not (
            customizations.get(str(positions[index]) if by_position else _value_key(result, positions[index])) or {}
        ).get("hidden")
    ]


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _as_number(value: Any) -> float | None:
    if value is None:
        return 0.0
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        return None
    return float(value)


def _sql_period(days: list[date], week_start_day: int | None) -> str | None:
    gaps = {(later - earlier).days for earlier, later in zip(days, days[1:])}
    if not gaps:
        return None
    if min(gaps) == 1:
        return "day"
    first_weekday = 0 if week_start_day == WeekStartDay.MONDAY else 6
    if gaps == {7} and all(day.weekday() == first_weekday for day in days):
        return "week"
    months = [day.year * 12 + day.month for day in days]
    if all(day.day == 1 for day in days) and all(later - earlier == 1 for earlier, later in zip(months, months[1:])):
        return "month"
    return None


def _sql_series(
    team: Team,
    user: User,
    *,
    short_id: str,
    name: str | None,
    query: dict[str, Any],
    filters: dict[str, Any],
    variables: dict[str, Any] | None,
) -> InsightSeries | None:
    settings = query.get("chartSettings") or {}
    x_column = (settings.get("xAxis") or {}).get("column")
    y_axes = [axis for axis in settings.get("yAxis") or [] if axis.get("column")]
    if query.get("display") not in CHARTED_SQL_DISPLAYS or not x_column or not y_axes:
        return None
    response = _run(team, user, query["source"], filters, variables)
    columns = response.get("columns") or []
    breakdown_column = settings.get("seriesBreakdownColumn")
    wanted = [x_column, *(axis["column"] for axis in y_axes), *([breakdown_column] if breakdown_column else [])]
    if response.get("hasMore") or any(column not in columns for column in wanted):
        return None
    position = {column: index for index, column in enumerate(columns)}
    labels: dict[tuple[int, str | None], str] = {}
    series: dict[tuple[int, str | None], dict[date, float]] = {}
    for row in response.get("results") or []:
        day = _as_date(row[position[x_column]])
        if day is None:
            return None
        for index, axis in enumerate(y_axes):
            value = _as_number(row[position[axis["column"]]])
            if value is None:
                return None
            breakdown = str(row[position[breakdown_column]]) if breakdown_column else None
            key = (index, breakdown)
            if key not in labels:
                label = str(((axis.get("settings") or {}).get("display") or {}).get("label") or axis["column"])
                if breakdown is not None:
                    label = f"{label} · {breakdown}" if len(y_axes) > 1 else breakdown
                while label in labels.values():
                    label += " (2)"
                labels[key] = label
            points = series.setdefault(key, {})
            if day in points:
                return None
            points[day] = value
    period = _sql_period(sorted({day for points in series.values() for day in points}), team.week_start_day)
    if period is None:
        return None
    formatting = ((y_axes[0].get("settings") or {}).get("formatting") or {}) if len(y_axes) == 1 else {}
    places = formatting.get("decimalPlaces")
    return InsightSeries(
        short_id=short_id,
        name=name,
        series={labels[key]: sorted(points.items()) for key, points in series.items()},
        period=period,
        averaged_series=[labels[key] for key in series],
        event_name="",
        value_format="percentage_scaled" if formatting.get("style") == "percent" else None,
        value_prefix=formatting.get("prefix") or None,
        value_postfix=formatting.get("suffix") or None,
        decimal_places=None if places is None else min(max(int(places), 0), 9),
    )


def insight_series(
    team: Team,
    user: User,
    *,
    short_id: str,
    name: str | None,
    query: dict[str, Any],
    dashboard: InsightDashboardContext | None,
) -> InsightSeries | None:
    dashboard_filters: dict[str, Any] = {}
    variables: dict[str, Any] | None = None
    if dashboard is not None:
        effective = resolve_effective_dashboard_filters(query, dashboard.filters, dashboard.tile_filters)
        query = effective.query
        dashboard_filters = effective.filters or {}
        variables = dashboard.variables
    filters = {key: value for key, value in dashboard_filters.items() if key not in DATE_FILTERS}
    source = query.get("source", query)
    if query.get("kind") == "DataVisualizationNode" and source.get("kind") == "HogQLQuery":
        return _sql_series(team, user, short_id=short_id, name=name, query=query, filters=filters, variables=variables)
    trends = source.get("trendsFilter") or {}
    if source.get("kind") != "TrendsQuery" or trends.get("display") in UNCHARTED_DISPLAYS:
        return None
    interval = dashboard_filters.get("interval") or source.get("interval") or "day"
    if interval not in LOOKBACK:
        interval = "day"
    date_range = source.get("dateRange") or {}
    if interval == "day" and date_range.get("daysOfWeek"):
        return None
    kept = {key: value for key, value in date_range.items() if key not in DATE_FILTERS}
    bounded = {key: value for key, value in source.items() if key != "compareFilter"}
    bounded.update(
        interval=interval,
        dateRange={**kept, "date_from": LOOKBACK[interval], "excludeIncompletePeriods": True},
        trendsFilter={**{k: v for k, v in trends.items() if k != "smoothingIntervals"}, "metricShowChange": False},
    )
    response = _run(team, user, bounded, filters, variables)
    formula = bool(trends.get("formula") or trends.get("formulas") or trends.get("formulaNodes"))
    several = len(source.get("series") or []) > 1
    series: dict[str, list[tuple[date, float]]] = {}
    averaged: list[str] = []
    for result in _visible(trends, response.get("results") or []):
        if not result.get("days"):
            continue
        action = result.get("action") or {}
        shown = str(result.get("label") or "Series")
        label = str(action.get("custom_name") or action.get("name") or shown)
        breakdown = result.get("breakdown_value")
        if breakdown not in (None, ""):
            if action:
                value = shown.removeprefix(f"{action.get('name')} - ") if several else shown
            else:
                value = ", ".join(str(b) for b in breakdown) if isinstance(breakdown, list) else str(breakdown)
            label = f"{label} · {value}" if several else value
        while label in series:
            label += " (2)"
        series[label] = [
            (date.fromisoformat(str(d)[:10]), float(v or 0)) for d, v in zip(result["days"], result["data"])
        ]
        if formula or (action.get("math") or "total") not in ADDITIVE_MATH:
            averaged.append(label)
    if not series:
        return None
    nodes = source.get("series") or []
    node = nodes[0] if len(nodes) == 1 else {}
    places = trends.get("decimalPlaces")
    return InsightSeries(
        short_id=short_id,
        name=name,
        series=series,
        period=interval,
        averaged_series=averaged,
        event_name=str(node.get("custom_name") or node.get("event") or node.get("name") or ""),
        value_format=trends.get("aggregationAxisFormat"),
        value_prefix=trends.get("aggregationAxisPrefix"),
        value_postfix=trends.get("aggregationAxisPostfix"),
        decimal_places=None if places is None else min(max(int(places), 0), 9),
    )
